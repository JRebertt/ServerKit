# Distro compatibility baseline — 2026-08-28

This is the first broad ServerKit compatibility discovery run from Windows 10
using Docker Desktop 29.7.2 (`linux/amd64`). It records observed evidence; it
does not change the installer or redefine the published support labels.

Command:

```powershell
python .\scripts\test\distro-compatibility.py --mode both --jobs 4
```

## Numbers

- Published catalog: **25/25 targets** — 5 Tested, 9 Supported, 11 Community.
- Runnable container probes: **25 images** — 22 exact distro/version images
  and 3 vendor userland proxies.
- Checks executed: **50** — 44 passed, 6 failed, 0 infrastructure errors.
- Quick source/syntax checks: **22/25 passed**.
- Real Python repository provisioning: **22/25 passed**.
- Published **Tested** group: **5/5 target families passed both available
  container layers** (Ubuntu, Debian, Fedora, Rocky Linux, AlmaLinux).
- ServerKit all-in-one Docker artifact: **12/12 smoke assertions passed** after
  a Windows-native build and boot through Docker Desktop.
- WSL2 Ubuntu 24.04.2: **non-destructive quick suite passed** with systemd in
  the `running` state. Package provisioning/full install was intentionally not
  run against the developer's active WSL distribution.

A quick pass is not an install pass. It covers shell syntax and ServerKit's
source-level installer/update/lib/CLI suites. A provisioning pass means the
real repositories supplied a Python in ServerKit's 3.11–3.13 gate, and that it
created a venv with pip, SSL, SQLite, and ctypes.

## Concrete results

| Image probe | Fidelity | Quick | Python provisioning | What this says |
|---|---|---:|---:|---|
| Ubuntu 22.04 | exact | pass | pass | Both container layers pass. |
| Ubuntu 24.04 | exact | pass | pass | Both container layers pass. |
| Debian 12 | exact | pass | pass | Both container layers pass. |
| Debian 13 | exact | pass | pass | Both container layers pass. |
| Fedora 38 | exact | pass | pass | Both container layers pass; no lifecycle/EOL claim is implied. |
| Fedora 39 | exact | pass | pass | Both container layers pass; no lifecycle/EOL claim is implied. |
| Fedora 40 | exact | pass | pass | Both container layers pass; no lifecycle/EOL claim is implied. |
| Fedora 41 | exact | pass | pass | Both container layers pass; no lifecycle/EOL claim is implied. |
| Rocky Linux 9 | exact | pass | pass | Both container layers pass. |
| Rocky Linux 10 | exact | pass | pass | Both container layers pass. |
| AlmaLinux 9 | exact | pass | pass | Both container layers pass. |
| AlmaLinux 10 | exact | pass | pass | Both container layers pass. |
| RHEL 9 UBI | proxy | pass | pass | RHEL-compatible userland only; not subscription/repository proof. |
| RHEL 10 UBI | proxy | pass | pass | RHEL-compatible userland only; not subscription/repository proof. |
| CentOS Stream 9 | exact | pass | pass | Both container layers pass. |
| CentOS Stream 10 | exact | pass | pass | Both container layers pass. |
| Oracle Linux 9 | exact | pass | pass | Userland passes; the UEK kernel is outside a container. |
| Amazon Linux 2023 | exact | **fail** | pass | Quick image lacks `find`; five update-suite assertions fail. Python is usable. |
| openSUSE Leap 15.5 | exact | pass | pass | Both container layers pass. |
| openSUSE Leap 15.6 | exact | pass | pass | Both container layers pass. |
| openSUSE Tumbleweed | exact | **fail** | pass | Minimal image lacks `find`/`awk`; the quick suite cannot run cleanly. Python is usable. |
| SLES 15 SP7 BCI | proxy | **fail** | pass | Minimal BCI lacks `awk`; SLES userland proxy only. Python is usable. |
| Arch Linux rolling | exact | pass | **fail** | Current repo Python is 3.14.7, outside the 3.11–3.13 gate; fallback package names also do not match Arch. |
| Manjaro rolling | exact | pass | **fail** | Image Python is 3.14.3, outside the 3.11–3.13 gate; fallback package names also do not match Arch. |
| Gentoo stage3 | exact | pass | **fail** | Detection exits before provisioning because `emerge` is not a supported installer package-manager path. |

## What remains unproven

The Windows/Docker run gives base-proxy evidence, not exact evidence, for
Raspberry Pi OS, Linux Mint, Pop!_OS, Zorin OS, elementary OS, and Proxmox VE.
Those need arm64 hardware/CI or disposable Hyper-V VMs with their actual media.

Docker, LXC/Incus, virtual-machine behavior, and WSL2 are platform targets, not
plain distro images. They remain separate tracks:

- Docker: **passed in this baseline** — `scripts/test/smoke-docker-image.sh`
  built the image, booted it, reached health, served the SPA and both agent
  installers, and passed 12/12 assertions.
- Hyper-V guests: `scripts/test/full-stack-test.ps1` via Multipass/Vagrant.
- WSL2: the source-level suite passed on Ubuntu 24.04.2 with a WSL2 kernel and
  running systemd. A real install still needs a disposable `wsl --import`
  distribution, not the developer's active WSL installation.
- LXC/Incus and Proxmox nesting: a Linux/nested-Proxmox host with nesting and
  keyctl controls.
- Raspberry Pi OS: native arm64 CI for architecture-sensitive logic plus a
  physical 64-bit Pi for final evidence.

The generated per-check logs and JSON for this run are under the ignored local
artifact directory `scripts/test/output/distro-compatibility/20260828-223431/`.
Future scheduled discovery runs upload the equivalent report as a GitHub
Actions artifact without turning known failures green.
