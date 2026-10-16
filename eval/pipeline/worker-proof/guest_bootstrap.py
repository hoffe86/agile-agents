"""Trusted, immutable entrypoint. Never import this to execute code on the host.

Guest seccomp is separate from runsc's HOST seccomp. Linux amd64 only.
Filter installation failure MUST prevent exec of /input/task.py.
"""

import ctypes
import errno
import os
import platform
import resource
import stat
import sys


def install_filter():
    if platform.machine() != "x86_64" or sys.platform != "linux":
        raise RuntimeError("UNSUPPORTED_GUEST_ARCH")

    class Instruction(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32),
        ]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort),
                    ("filter", ctypes.POINTER(Instruction))]

    # seccomp_data: nr @0, audit architecture @4. Reject alternate ABI/x32.
    # BPF_LD|W|ABS, JMP|JEQ|K, RET|K, JMP|JGE|K; EPERM for deny.
    deny = 0x00050000 | errno.EPERM
    instructions = [
        (0x20, 0, 0, 4), (0x15, 1, 0, 0xC000003E),
        (0x06, 0, 0, deny), (0x20, 0, 0, 0),
        (0x35, 0, 1, 0x40000000), (0x06, 0, 0, deny),
    ]
    # socket, connect, accept, sendto/recvfrom/sendmsg/recvmsg, shutdown,
    # bind/listen, name/options, socketpair, accept4, recvmmsg/sendmmsg,
    # io_uring_setup (can create sockets), ptrace and process_vm_writev.
    # Deny all socket operations as defense against inherited descriptors.
    for number in [*range(41, 56), 101, 288, 299, 307, 311, 425]:
        instructions.extend([(0x15, 0, 1, number), (0x06, 0, 0, deny)])
    instructions.append((0x06, 0, 0, 0x7FFF0000))
    code = (Instruction * len(instructions))(
        *(Instruction(*instruction) for instruction in instructions))
    program = Program(len(code), code)
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_NO_NEW_PRIVS, then PR_SET_SECCOMP / SECCOMP_MODE_FILTER.
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "NO_NEW_PRIVS_FAILED")
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "GUEST_SECCOMP_FAILED")
    if libc.prctl(21, 0, 0, 0, 0) != 2:
        raise RuntimeError("GUEST_SECCOMP_NOT_ACTIVE")


def main():
    try:
        if os.getuid() != 65532 or os.getgid() != 65532:
            raise RuntimeError("NONROOT_REQUIRED")
        for fd in (0, 1, 2):
            if stat.S_ISSOCK(os.fstat(fd).st_mode):
                raise RuntimeError("SOCKET_STDIO_FORBIDDEN")
        os.closerange(3, 65536)
        os.umask(0o077)
        # Defense-in-depth requested limit, NOT evidence of enforcement:
        # pinned gVisor sys_rlimit.go explicitly does not enforce ProcessCount.
        # The native process-pressure test therefore remains a blocking gate.
        resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        install_filter()
        os.chdir("/scratch")
        os.execve("/usr/local/bin/python3",
                  ["python3", "-I", "-B", "/input/task.py"],
                  {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/scratch",
                   "TMPDIR": "/scratch", "LANG": "C.UTF-8"})
    except Exception as exc:
        print(f"WORKER_STARTUP_DENIED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    sys.exit(main())
