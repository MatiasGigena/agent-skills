"""Private-pipe protocol and real Git capture tests; no provider credentials."""
import importlib.machinery
import importlib.util
import itertools
import json
import os
import select
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "autoreview"
LOADER = importlib.machinery.SourceFileLoader("native_autoreview", str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
LOADER.exec_module(M)


def send(sock, value):
    data = json.dumps({"protocol": M.NATIVE_PROTOCOL, **value}).encode()
    sock.sendall(len(data).to_bytes(4, "big") + data)


def read(sock):
    def exact(size):
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise EOFError()
            data.extend(chunk)
        return bytes(data)
    size = int.from_bytes(exact(4), "big")
    if not 0 < size <= M.MAX_NATIVE_FRAME_BYTES:
        raise AssertionError("unbounded frame")
    return json.loads(exact(size))


class StdioHost:
    def __init__(self, proc):
        self.input = proc.stdin
        self.output = proc.stdout

    def sendall(self, data):
        self.input.write(data)
        self.input.flush()

    def recv(self, size):
        if not select.select([self.output], [], [], 10)[0]:
            raise TimeoutError("native fixture did not send its next frame")
        return os.read(self.output.fileno(), size)

    def close(self):
        self.input.close()
        self.output.close()


@unittest.skipUnless(os.name == "posix", "inherited POSIX transport")
class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.host, self.guest = socket.socketpair()
        self.host.settimeout(10)
        self.addCleanup(self.host.close)
        self.addCleanup(self.guest.close)
        self.transport = M.NativeReviewTransport(self.guest.fileno(), 1)
        self.transport.capture_id = "capture"

    def test_header_limit_before_body_read(self):
        self.host.sendall((M.MAX_NATIVE_FRAME_BYTES + 1).to_bytes(4, "big"))
        with self.assertRaisesRegex(M.ReviewerUnavailable, "byte limit"):
            self.transport.receive()

    def test_git_children_retain_only_valid_nonsecret_cleanup_membership(self):
        marker = "12345678-1234-4234-8234-123456789abc"
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            environment = {"PATH": os.environ["PATH"], "HOME": directory,
                           "CODEX_SANDBOX_EXEC_ID": marker, "CODEX_API_KEY": "fixture-token",
                           "GH_TOKEN": "fixture-token", "CODEX_OTHER": "fixture-value"}
            with mock.patch.dict(os.environ, environment, clear=True):
                env = M.safe_git_env(repo)
                child = subprocess.run([sys.executable, "-I", "-c",
                    "import json,os; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith(('CODEX_', 'GH_'))}))"],
                    env=env, check=True, capture_output=True, text=True)
                self.assertEqual(json.loads(child.stdout), {"CODEX_SANDBOX_EXEC_ID": marker})
                for invalid in ("", marker.upper(), marker + "\n", "not-a-uuid"):
                    os.environ["CODEX_SANDBOX_EXEC_ID"] = invalid
                    self.assertNotIn("CODEX_SANDBOX_EXEC_ID", M.safe_git_env(repo))

    def test_aggregate_output_limit(self):
        self.transport.output_bytes = M.MAX_NATIVE_OUTPUT_BYTES
        self.host.sendall((1).to_bytes(4, "big"))
        with self.assertRaisesRegex(M.ReviewerUnavailable, "byte limit"):
            self.transport.receive()

    def test_utf8_and_protocol_and_capture_rejected(self):
        for response in ({"captureId": "other"}, {"captureId": "capture", "protocol": "v0"}):
            send(self.host, response)
            with self.assertRaisesRegex(M.ReviewerUnavailable, "match this capture"):
                self.transport.receive()
        self.host.sendall(b"\x00\x00\x00\x01\xff")
        with self.assertRaisesRegex(M.ReviewerUnavailable, "invalid frame"):
            self.transport.receive()

    def test_eof_and_deadline(self):
        self.host.close()
        with self.assertRaisesRegex(M.ReviewerUnavailable, "closed"):
            self.transport.receive()
        self.transport.deadline = 0
        with self.assertRaisesRegex(M.ReviewerUnavailable, "deadline"):
            self.transport.remaining()

    def test_wrong_pass_cannot_be_used_as_completion(self):
        self.transport.pass_count = 1
        send(self.host, {"captureId": "capture", "kind": "completion", "pass": 2,
                         "text": "{}", "promptSha256": "unrelated"})
        with self.assertRaisesRegex(M.ReviewerUnavailable, "current pass"):
            self.transport.review("prompt")

    def test_oversized_terminal_report_is_not_sent(self):
        self.transport.pass_index = self.transport.pass_count = 1
        with self.assertRaisesRegex(M.ReviewerUnavailable, "frame exceeds"):
            self.transport.finish({"report": "x" * M.MAX_NATIVE_FRAME_BYTES}, 0)

    def test_complete_git_capture_and_terminal_outcomes(self):
        outcomes = ("complete", "incomplete", "invalid", "source-drift", "evidence-drift", "terminal-close", "root-mismatch")
        for outcome, transport in itertools.product(outcomes, ("fd", "stdio")):
            with self.subTest(outcome=outcome, transport=transport), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory) / "repo"
                repo.mkdir()
                status = Path(directory) / "status.json"
                def git(*args):
                    return subprocess.run(["git", *args], cwd=repo, check=True,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                git("init", "-q")
                git("config", "user.name", "Review fixture")
                git("config", "user.email", "fixture@example.invalid")
                source = repo / "source.py"
                source.write_text("value = 1\n")
                context = repo / "context.txt"
                context.write_text("bounded caller contract\n")
                git("add", ".")
                git("commit", "-qm", "fixture")
                base = git("rev-parse", "HEAD").stdout.decode().strip()
                source.write_text("value = 2\n")
                git("add", "source.py")
                source.write_text("value = 3\n")
                (repo / "new.py").write_text("new_value = 4\n")
                host, child = socket.socketpair()
                host.settimeout(10)
                workdir = repo
                if outcome == "root-mismatch":
                    workdir = repo / "subdirectory"
                    workdir.mkdir()
                pipe_args = ["--native-stdio"] if transport == "stdio" else ["--native-fd", str(child.fileno())]
                errors = tempfile.TemporaryFile()
                proc = subprocess.Popen(
                    [sys.executable, "-I", str(SOURCE), "--mode", "local", "--base", base, "--engine", "native",
                     *pipe_args, "--engine-timeout-seconds", "10",
                     "--dataset", "context.txt", "--status-output", str(status)], cwd=workdir,
                    pass_fds=() if transport == "stdio" else (child.fileno(),),
                    stdin=subprocess.PIPE if transport == "stdio" else subprocess.DEVNULL,
                    stdout=subprocess.PIPE if transport == "stdio" else subprocess.DEVNULL, stderr=errors,
                    env={"PATH": os.environ["PATH"], "HOME": directory})
                child.close()
                if transport == "stdio":
                    host.close()
                    host = StdioHost(proc)
                final = None
                try:
                    if outcome == "root-mismatch":
                        with self.assertRaises(EOFError):
                            read(host)
                        proc.wait(timeout=10)
                        self.assertNotEqual(proc.returncode, 0)
                        errors.seek(0)
                        self.assertIn(b"root must match", errors.read())
                        continue
                    capture = read(host)
                    self.assertEqual(capture["kind"], "capture")
                    self.assertEqual(capture["capture"]["base"], base)
                    self.assertEqual(capture["capture"]["head"], git("rev-parse", "HEAD").stdout.decode().strip())
                    self.assertNotEqual(capture["capture"]["index"], capture["capture"]["workingTree"])
                    self.assertEqual(capture["capture"]["evidence"][0]["path"], "context.txt")
                    send(host, {"kind": "ready", "captureId": capture["captureId"]})
                    for _ in range(capture["passCount"]):
                        request = read(host)
                        self.assertEqual(request["kind"], "review")
                        self.assertIn("source.py", request["prompt"])
                        report = {"findings": [], "overall_correctness": "patch is correct",
                                  "overall_explanation": "The supplied changes are consistent.",
                                  "overall_confidence": 0.9,
                                  "review_completion": "incomplete" if outcome == "incomplete" else "complete"}
                        if outcome == "source-drift":
                            source.write_text("value = 5\n")
                        if outcome == "evidence-drift":
                            context.write_text("changed contract\n")
                        send(host, {"kind": "completion", "captureId": request["captureId"],
                                    "pass": request["pass"], "promptSha256": request["promptSha256"],
                                    "text": "{}" if outcome == "invalid" else json.dumps(report)})
                    if outcome == "terminal-close":
                        host.close()
                    else:
                        try:
                            final = read(host)
                        except EOFError:
                            pass
                    proc.wait(timeout=10)
                    errors.seek(0)
                    error = errors.read()
                    if outcome == "complete":
                        self.assertEqual(proc.returncode, 0, error.decode())
                        self.assertEqual(final["report"]["review_status"], "scoped-clean")
                    elif outcome == "incomplete":
                        self.assertEqual(proc.returncode, 2, error.decode())
                        self.assertEqual(final["report"]["review_status"], "incomplete")
                    else:
                        self.assertNotEqual(proc.returncode, 0)
                        self.assertIsNone(final)
                        if outcome == "terminal-close":
                            self.assertEqual(json.loads(status.read_text())["status"], "reviewer_unavailable")
                finally:
                    host.close()
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait(timeout=10)
                    errors.close()


if __name__ == "__main__":
    unittest.main()
