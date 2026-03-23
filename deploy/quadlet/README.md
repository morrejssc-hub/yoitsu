# Yoitsu Quadlet Dev Pod

This is a Podman Quadlet deployment for the current development phase:

- One long-lived service pod plus one short-lived Podman container per job.
- The long-lived service repos are bind-mounted read-only into the containers.
- Pasloe and Trenni bootstrap their Python virtualenvs into persistent Podman volumes on first start.
- The `trenni` container copies only the `trenni` source tree into a writable state volume before installing it.
- Job execution happens through the rootless Podman REST API, not `subprocess`.
- Topology is `1 pod / 2 long-lived containers / N job containers`:
  - `pasloe` container
  - `trenni` container
  - dynamic `palimpsest` job containers created by `trenni`

## Layout

- `yoitsu.pod`: shared pod with ports `8000` and `8100` published on loopback.
- `yoitsu-pasloe.container`: Pasloe service.
- `yoitsu-trenni.container`: Trenni service plus Podman control-plane access.
- `yoitsu-pasloe-data.volume`: SQLite/event data.
- `yoitsu-dev-state.volume`: shared state for HOME and service venvs.
- `trenni.dev.yaml`: container-oriented Trenni config.
- `bin/start-pasloe.sh`: Pasloe bootstrap/start wrapper.
- `bin/start-trenni.sh`: Trenni bootstrap/start wrapper.
- `../podman/palimpsest-job.Containerfile`: job image build file.

## Assumptions

- Rootless Podman + Quadlet.
- This repo lives at `%h/yoitsu`.
- User Quadlet files live under `~/.config/containers/systemd/`.
- The rootless Podman API socket is available through `podman.socket`.
- A local job image named `localhost/yoitsu-palimpsest-job:dev` exists.

## Environment Files

Sync the application directory into the Quadlet tree, then edit the env files:

```bash
mkdir -p ~/.config/containers/systemd/yoitsu
install -m 0644 deploy/quadlet/yoitsu.pod ~/.config/containers/systemd/yoitsu/yoitsu.pod
install -m 0644 deploy/quadlet/yoitsu-pasloe.container ~/.config/containers/systemd/yoitsu/yoitsu-pasloe.container
install -m 0644 deploy/quadlet/yoitsu-trenni.container ~/.config/containers/systemd/yoitsu/yoitsu-trenni.container
install -m 0644 deploy/quadlet/yoitsu-pasloe-data.volume ~/.config/containers/systemd/yoitsu/yoitsu-pasloe-data.volume
install -m 0644 deploy/quadlet/yoitsu-dev-state.volume ~/.config/containers/systemd/yoitsu/yoitsu-dev-state.volume
install -m 0644 deploy/quadlet/trenni.dev.yaml ~/.config/containers/systemd/yoitsu/trenni.dev.yaml
install -m 0644 deploy/quadlet/pasloe.env.example ~/.config/containers/systemd/yoitsu/pasloe.env.example
install -m 0644 deploy/quadlet/trenni.env.example ~/.config/containers/systemd/yoitsu/trenni.env.example
install -d ~/.config/containers/systemd/yoitsu/bin
install -m 0755 deploy/quadlet/bin/start-pasloe.sh ~/.config/containers/systemd/yoitsu/bin/start-pasloe.sh
install -m 0755 deploy/quadlet/bin/start-trenni.sh ~/.config/containers/systemd/yoitsu/bin/start-trenni.sh
install -m 0755 deploy/quadlet/bin/health-pasloe.sh ~/.config/containers/systemd/yoitsu/bin/health-pasloe.sh
install -m 0755 deploy/quadlet/bin/health-trenni.sh ~/.config/containers/systemd/yoitsu/bin/health-trenni.sh
cp ~/.config/containers/systemd/yoitsu/pasloe.env.example ~/.config/containers/systemd/yoitsu/pasloe.env
cp ~/.config/containers/systemd/yoitsu/trenni.env.example ~/.config/containers/systemd/yoitsu/trenni.env
chmod 600 ~/.config/containers/systemd/yoitsu/pasloe.env ~/.config/containers/systemd/yoitsu/trenni.env
```

Required values:

- `~/.config/containers/systemd/yoitsu/pasloe.env`
  - `API_KEY`
  - `SQLITE_PATH` (default already points at the volume)

- `~/.config/containers/systemd/yoitsu/trenni.env`
  - `PASLOE_API_KEY`
  - `OPENAI_API_KEY`
  - optional `GITHUB_TOKEN`

## Preferred Workflow

Preferred host-side flow:

```bash
./scripts/build-job-image.sh
./scripts/deploy-quadlet.sh
./scripts/quadlet-status.sh
```

The rest of this document shows the equivalent manual commands.

## Build The Job Image

Build the image that Trenni will launch for each job:

```bash
cd ~/yoitsu
podman build -t localhost/yoitsu-palimpsest-job:dev \
  -f deploy/podman/palimpsest-job.Containerfile .
```

## Install

Install the Quadlet app directory into the user scope:

```bash
mkdir -p ~/.config/containers/systemd/yoitsu
install -m 0644 deploy/quadlet/yoitsu.pod ~/.config/containers/systemd/yoitsu/yoitsu.pod
install -m 0644 deploy/quadlet/yoitsu-pasloe.container ~/.config/containers/systemd/yoitsu/yoitsu-pasloe.container
install -m 0644 deploy/quadlet/yoitsu-trenni.container ~/.config/containers/systemd/yoitsu/yoitsu-trenni.container
install -m 0644 deploy/quadlet/yoitsu-pasloe-data.volume ~/.config/containers/systemd/yoitsu/yoitsu-pasloe-data.volume
install -m 0644 deploy/quadlet/yoitsu-dev-state.volume ~/.config/containers/systemd/yoitsu/yoitsu-dev-state.volume
install -m 0644 deploy/quadlet/trenni.dev.yaml ~/.config/containers/systemd/yoitsu/trenni.dev.yaml
install -m 0644 deploy/quadlet/pasloe.env.example ~/.config/containers/systemd/yoitsu/pasloe.env.example
install -m 0644 deploy/quadlet/trenni.env.example ~/.config/containers/systemd/yoitsu/trenni.env.example
install -d ~/.config/containers/systemd/yoitsu/bin
install -m 0755 deploy/quadlet/bin/start-pasloe.sh ~/.config/containers/systemd/yoitsu/bin/start-pasloe.sh
install -m 0755 deploy/quadlet/bin/start-trenni.sh ~/.config/containers/systemd/yoitsu/bin/start-trenni.sh
install -m 0755 deploy/quadlet/bin/health-pasloe.sh ~/.config/containers/systemd/yoitsu/bin/health-pasloe.sh
install -m 0755 deploy/quadlet/bin/health-trenni.sh ~/.config/containers/systemd/yoitsu/bin/health-trenni.sh
systemctl --user daemon-reload
systemctl --user start podman.socket yoitsu-pod.service yoitsu-pasloe.service yoitsu-trenni.service
```

Equivalent helper:

```bash
./scripts/deploy-quadlet.sh
```

Quadlet-generated services are transient. Keep the source files under the user
Quadlet search path and let the generator apply their `[Install]` metadata on
`daemon-reload`.

## Operations

Status:

```bash
./scripts/quadlet-status.sh

systemctl --user status yoitsu-pasloe.service yoitsu-trenni.service
podman pod ps
podman ps
```

Logs:

```bash
journalctl --user -u yoitsu-pasloe.service -f
journalctl --user -u yoitsu-trenni.service -f
```

Stop:

```bash
systemctl --user stop yoitsu-trenni.service yoitsu-pasloe.service
```

## Notes

- First boot is slower because the wrappers create venvs, copy source into the
  writable state volume, and reinstall wheels from that copy.
- Source changes in the mounted repo are picked up on service restart because
  the wrapper recopies the Trenni source tree and reinstalls the package.
- The component repo mounts are read-only; mutable runtime state stays inside the
  named volume or inside per-job containers.
- `pasloe` is isolated in its own container so event storage stays up even if the
  job-running side is unstable.
- `trenni` is the control plane. It launches one short-lived sibling container
  per job into pod `yoitsu-dev` and removes completed containers by policy.
