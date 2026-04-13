# Yoitsu Quadlet Dev Pod

This deployment is the current development target for the redesigned stack:

- one long-lived `postgres` service container
- one long-lived `pasloe` service container
- one long-lived `trenni` service container
- one short-lived `palimpsest` Podman container per job
- rootless Podman REST API as the isolation control plane

The architecture now matches the code split:

- scheduling and replay stay in `trenni`
- environment injection happens before launch
- the runtime image only executes one job

## Files

- `yoitsu.pod`: shared pod publishing `8000` and `8100`
- `yoitsu-postgres.container`: PostgreSQL service unit
- `yoitsu-pasloe.container`: Pasloe service unit
- `yoitsu-trenni.container`: Trenni service unit with Podman API access
- `yoitsu-postgres-data.volume`: PostgreSQL data
- `yoitsu-pasloe-data.volume`: event store data
- `yoitsu-dev-state.volume`: persistent service state and venvs
- `trenni.dev.yaml`: container-oriented Trenni config
- `bin/start-pasloe.sh`: Pasloe bootstrap
- `bin/start-trenni.sh`: Trenni bootstrap
- `../podman/palimpsest-job.Containerfile`: Palimpsest job image build

## Assumptions

- rootless Podman and Quadlet are installed
- the repo lives at `~/yoitsu`
- user Quadlet files live under `~/.config/containers/systemd/yoitsu`
- `podman.socket` is available
- a local image `localhost/yoitsu-palimpsest-job:dev` exists

## Preferred Workflow

```bash
./scripts/build-job-image.sh
./scripts/deploy-quadlet.sh
systemctl --user status yoitsu-pod.service yoitsu-pasloe.service yoitsu-trenni.service
```

## Manual Install

```bash
mkdir -p ~/.config/containers/systemd/yoitsu
install -m 0644 deploy/quadlet/yoitsu.pod ~/.config/containers/systemd/yoitsu/yoitsu.pod
install -m 0644 deploy/quadlet/yoitsu-postgres.container ~/.config/containers/systemd/yoitsu/yoitsu-postgres.container
install -m 0644 deploy/quadlet/yoitsu-pasloe.container ~/.config/containers/systemd/yoitsu/yoitsu-pasloe.container
install -m 0644 deploy/quadlet/yoitsu-trenni.container ~/.config/containers/systemd/yoitsu/yoitsu-trenni.container
install -m 0644 deploy/quadlet/yoitsu-postgres-data.volume ~/.config/containers/systemd/yoitsu/yoitsu-postgres-data.volume
install -m 0644 deploy/quadlet/yoitsu-pasloe-data.volume ~/.config/containers/systemd/yoitsu/yoitsu-pasloe-data.volume
install -m 0644 deploy/quadlet/yoitsu-dev-state.volume ~/.config/containers/systemd/yoitsu/yoitsu-dev-state.volume
install -m 0644 deploy/quadlet/trenni.dev.yaml ~/.config/containers/systemd/yoitsu/trenni.dev.yaml
install -m 0644 deploy/quadlet/postgres.env.example ~/.config/containers/systemd/yoitsu/postgres.env.example
install -m 0644 deploy/quadlet/pasloe.env.example ~/.config/containers/systemd/yoitsu/pasloe.env.example
install -m 0644 deploy/quadlet/trenni.env.example ~/.config/containers/systemd/yoitsu/trenni.env.example
install -d ~/.config/containers/systemd/yoitsu/bin
install -m 0755 deploy/quadlet/bin/start-pasloe.sh ~/.config/containers/systemd/yoitsu/bin/start-pasloe.sh
install -m 0755 deploy/quadlet/bin/start-trenni.sh ~/.config/containers/systemd/yoitsu/bin/start-trenni.sh
install -m 0755 deploy/quadlet/bin/health-pasloe.sh ~/.config/containers/systemd/yoitsu/bin/health-pasloe.sh
install -m 0755 deploy/quadlet/bin/health-trenni.sh ~/.config/containers/systemd/yoitsu/bin/health-trenni.sh
cp ~/.config/containers/systemd/yoitsu/postgres.env.example ~/.config/containers/systemd/yoitsu/postgres.env
cp ~/.config/containers/systemd/yoitsu/pasloe.env.example ~/.config/containers/systemd/yoitsu/pasloe.env
cp ~/.config/containers/systemd/yoitsu/trenni.env.example ~/.config/containers/systemd/yoitsu/trenni.env
chmod 600 ~/.config/containers/systemd/yoitsu/postgres.env ~/.config/containers/systemd/yoitsu/pasloe.env ~/.config/containers/systemd/yoitsu/trenni.env
systemctl --user daemon-reload
systemctl --user start podman.socket yoitsu-pod.service yoitsu-postgres.service yoitsu-pasloe.service yoitsu-trenni.service
```

Required env values:

- `postgres.env`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
  - `POSTGRES_DB`
- `pasloe.env`
  - `API_KEY`
  - `DB_TYPE=postgres`
  - `PG_HOST`
  - `PG_PORT`
  - `PG_USER`
  - `PG_PASSWORD`
  - `PG_DB`
- `trenni.env`
  - `PASLOE_API_KEY`
  - `OPENAI_API_KEY`
  - optional `GITHUB_TOKEN`

## Build The Job Image

```bash
cd ~/yoitsu
podman build -t localhost/yoitsu-palimpsest-job:dev \
  -f deploy/podman/palimpsest-job.Containerfile .
```

## Operations

Status:

```bash
systemctl --user status yoitsu-postgres.service yoitsu-pasloe.service yoitsu-trenni.service
podman pod ps
podman ps
```

Logs:

```bash
journalctl --user -u yoitsu-pasloe.service -f
journalctl --user -u yoitsu-postgres.service -f
journalctl --user -u yoitsu-trenni.service -f
```

Stop:

```bash
systemctl --user stop yoitsu-trenni.service yoitsu-pasloe.service yoitsu-postgres.service
```

## Notes

- first boot is slower because the wrappers create persistent service venvs
- source changes are picked up on service restart because the wrapper recopies and reinstalls the service repo
- mutable state lives in the named volumes or in per-job containers, not in the read-only source mounts
- `trenni` now launches jobs through the Podman API only; the old subprocess deployment path is gone
