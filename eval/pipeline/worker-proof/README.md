# Independent no-model worker proof

This is **only `live-worker-proof`**, the approved disposable `ubuntu-24.04`
Docker + gVisor/systrap candidate for task05 (synthetic diff → Markdown).
It does not use the SDK, authenticate a provider, run evaluations, create a PR,
grant batch authorization, or remove `run-eval.*` holds. The controller proof
remains **BLOCKED**; grade2/provenance1 and scorer `UNVERIFIED` behavior are unchanged.

## Trust and lifetime

- Trusted preparation installs the official, checksum-locked **whole** gVisor
  release bundle, registers one fixed runtime, pulls the digest-pinned official
  Python image, and stages at most 1 MiB / 16 flat task-input files via a COPY-only
  build context. No arbitrary Dockerfile, RUN instruction, host artifact execution,
  host path bind, Docker socket, Copilot home, controller data, canonical reference
  criteria or secrets enter the worker.
- `worker.py` owns all runtime flags. Every task gets its own derived image,
  container, read-only input/toolchain, private PID/cgroup/network context, no
  capabilities, UID/GID 65532, no-new-privileges, 1 CPU, 1 GiB memory/no swap,
  and 128 host cgroup PIDs. `/scratch` is a 256 MiB noexec tmpfs. `/output` is
  an **8 MiB, task-owned Docker local-driver tmpfs volume**, not a host-path bind.
  This permits Docker's trusted archive API to read output while frozen without
  a `docker exec` escape around the entrypoint. There is no persistent data service.
- The immutable guest bootstrap requests hard limits (128 guest processes, 1 GiB
  address space, 8 MiB/file, 256 FDs, no cores), closes inherited non-stdio FDs,
  verifies stdio is not sockets, installs **guest** seccomp, then execs task code
  with exactly `PATH`, `HOME`, `TMPDIR`, `LANG`. Docker does not inherit runner
  environment; its client also receives a fixed credential-free environment.
  **Known blocker:** gVisor `release-20261005.0` explicitly does **not enforce**
  `RLIMIT_NPROC` (`ProcessCount` in `sys_rlimit.go`); a successful set/get is not
  a guest process bound. The native process-pressure test stays non-green.
- Socket denial covers socket/socketpair, all ordinary socket operations,
  io_uring creation, alternative ABI/x32, and is inherited across fork/exec.
  This is not a claim that Docker `--network none` or runsc's host seccomp
  filters enforce guest syscall policy. Guest seccomp failure prevents task exec.
  No target is contacted to prove isolation.
- One operation per task; the 60-second watchdog is stricter than the 15-minute
  task ceiling. Revocation is a terminal latch, checked before work and by a
  100 ms watchdog. Owned-container force removal is bounded to 8 seconds; failure
  is non-green, not silently ignored. The hosted job has a 30-minute timeout.
- The harness freezes the guest before bounded output acquisition and verifies
  Docker reports paused. After acquiring the immutable snapshot bytes it thaws
  **only for immediate removal**: native testing found runsc teardown cannot
  service Docker while frozen. No output is acquired after thaw. The host parses archive
  bytes as inert data: no extraction, no link following. Only 16 flat regular
  files totaling 1 MiB may leave; symlinks, hardlinks, directories, devices,
  FIFOs, duplicate names, absolute/traversal names and oversize data fail closed.
  Exported bytes are not trusted code and are never executed on the host.
- Every host/container canary is synthetic. Host process inspection in the guest
  searches only for the synthetic marker; no actual credential file is read.
  The runner still has platform control-plane access; separation relies on not
  passing it through to the worker, not on claiming the host is credential-free.

## Run without a model

Local, including Windows (stdlib only, no DeepEval environment required):

```text
python -m unittest discover -s eval/pipeline/worker-proof -p test_worker.py -v
```

Actual runtime tests are **only** for the disposable GitHub-hosted Linux job:
`.github/workflows/worker-proof.yml`. It is push/path/feature-branch scoped, has
no PR or dispatch trigger, pins checkout, does not persist checkout credentials,
has only `contents: read`, and supplies no provider, artifact, OIDC or session
credentials to the proof. Runtime installation requires root **there only**.
Do not run `setup_host.py` on a workstation or repair Docker/WSL settings.

The job prints `IDENTITIES`, per-task image/container identities and proof
results in native Actions logs. Its tests fail rather than skip when runsc,
guest filtering, cgroups, paused export or the expected runner identity is absent.
No plain-Docker fallback exists. Hosted logs/SHA are the runtime evidence;
passing mocked configuration tests is not runtime evidence.

## Acceptance mapping and current limits

| AC | Evidence/probe |
|---|---|
| 1: dependencies/host | `runtime.lock.json`; `setup_host.py` verifies bundle and every executable; `preflight` records actual runner, kernel, Docker, runsc, image digest/ID |
| 2: fixed credential-free isolation | `test_fixed_configuration_has_no_host_binds_or_network`, created-container validation, `test_01_allowed_work_and_boundaries` |
| 3: guest no sockets, inheritance | `test_01_allowed_work_and_boundaries`: AF_INET/INET6/UNIX/NETLINK, socketpair, connect/io_uring/x32 denial and exec descendant |
| 4: limits/lifecycle | `test_02_scratch_capacity`, `test_03_memory_and_process_bounds`, `test_08_cancellation_descendants_and_revocation`, `test_10_operation_deadline` |
| 5: export/reset/fail-closed | `test_04_reset`, hosted tests 05–09, pure output parser/input/runtime failure tests |
| 6: actual hosted test | scoped `worker-proof` workflow; native result must be recorded separately |
| 7: regressions | stdlib unittest, no existing test/assertion changed; no live/Waza/DeepEval command |

**Not claimed:** adversarial security certification, kernel/sentry escape
resistance proved by these probes, SDK mediation, live readiness, multi-operation
task scheduling, aggregate-memory pressure/OOM correctness, prompt revocation
across a wedged Docker daemon, or other benchmark capabilities. Configured CPU
and cgroup limits are not by themselves behavioral resource-pressure evidence.
The 15-minute ceiling is subsumed by one 60-second operation, not a tested
15-minute multi-operation workflow. A runner crash is handled by disposal, not
persistent recovery. No external fleet/cloud resources exist.

## Dependency and design basis

- [Official platforms guide](https://github.com/google/gvisor/blob/release-20261005.0/g3doc/user_guide/platforms.md):
  systrap works without nested virtualization; runtimeArgs selects the platform.
- [Official installation guide](https://github.com/google/gvisor/blob/release-20261005.0/g3doc/user_guide/install.md):
  current releases require companion files beside runsc; do not install only
  the old standalone binary.
- [Official release/checksums](https://github.com/google/gvisor/releases/tag/release-20261005.0):
  SHA256SUMS and release API digest independently matched the downloaded bundle;
  every member hash was calculated after verification. HTTPS publisher trust,
  **not independent signature attestation**, is the trust anchor.
- [Pinned guest seccomp implementation](https://github.com/google/gvisor/blob/release-20261005.0/pkg/sentry/syscalls/linux/sys_seccomp.go)
  and [prctl](https://github.com/google/gvisor/blob/release-20261005.0/pkg/sentry/syscalls/linux/sys_prctl.go):
  guest filters and no-new-privileges are implemented separately from host filters.
- [Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/),
  [pause](https://docs.docker.com/reference/cli/docker/container/pause/) and
  [volume create](https://docs.docker.com/reference/cli/docker/volume/create/).

The approved SDK/gVisor candidate is recorded by the user, not a newly authored
ADR. Existing ADR 0008/0015 evaluation separation and ADR 0003 test-bar asymmetry
remain intact. Profile decisions: `infrastructure.iac_tool: none`,
`infrastructure.deploy_verify: off` (no cloud apply),
`cicd.platform: github-actions`, `tech_stack.test_frameworks: unittest/pytest`.
Skills used: `read-repo-context`, `iac-best-practices`,
`cicd-pipeline-implementation`; gVisor-specific skill unavailable, so official
version-pinned source/documentation is used.

### Trade-offs

- Guest classic-BPF via stdlib ctypes rather than adding libseccomp/compiler
  packages: fewer mutable dependencies, but Linux amd64 syscall numbers require
  explicit ABI rejection and regression tests; revisit for another architecture.
- Dedicated bounded Docker tmpfs output volume rather than a writable host
  directory or in-guest export process: preserves freeze-before-export without
  worker filesystem access to the host; Docker daemon/archive handling stays trusted.

## Cleanup

The context manager removes only exact task-owned container, volume and derived
image names. It does not prune Docker or delete unrelated resources. Runtime
bundle, registered runtime, pulled base image, and COPY-only build cache exist
only on the disposable runner and disappear with the VM. No local SDK environment,
historic artifacts, archive tags or other author's changes are modified.
