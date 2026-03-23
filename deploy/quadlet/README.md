# Yoitsu Quadlet Dev Pod

This is a Podman Quadlet deployment for the current development phase:

- No custom app image builds.
- The three component repos are bind-mounted read-only into the containers.
- Pasloe and Trenni bootstrap their Python virtualenvs into persistent Podman volumes on first start.
- The `trenni` container copies source trees into a writable state volume before installing them.
- The current Quadlet deployment disables inner `bubblewrap` and uses `subprocess` for job launch. See `docs/adr/0003-podman-quadlet-subprocess-deployment.md`.
- Topology is `1 pod / 2 containers / 3 repos`:
  - `pasloe` container
  - `trenni` container
  - `palimpsest` runs as subprocesses inside the `trenni` container

## Layout

- `yoitsu.pod`: shared pod with ports `8000` and `8100` published on loopback.
- `yoitsu-pasloe.container`: Pasloe service.
- `yoitsu-trenni.container`: Trenni service plus Palimpsest runtime subprocesses.
- `yoitsu-pasloe-data.volume`: SQLite/event data.
- `yoitsu-dev-state.volume`: shared state for Trenni workdir, HOME, and service venvs.
- `trenni.dev.yaml`: container-oriented Trenni config.
- `bin/start-pasloe.sh`: Pasloe bootstrap/start wrapper.
- `bin/start-trenni.sh`: Trenni bootstrap/start wrapper.

## Assumptions

- Rootless Podman + Quadlet.
- This repo lives at `%h/yoitsu`.
- User Quadlet files live under `~/.config/containers/systemd/`.
- We are validating application behavior before re-introducing a second
  in-container sandbox layer.

## Environment Files

Sync the application directory into the Quadlet tree, then edit the env files:

```bash
mkdir -p ~/.config/containers/systemd/yoitsu
cp -r deploy/quadlet/* ~/.config/containers/systemd/yoitsu/
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

## Install

Install the Quadlet app directory into the user scope:

```bash
mkdir -p ~/.config/containers/systemd/yoitsu
cp -r deploy/quadlet/* ~/.config/containers/systemd/yoitsu/
systemctl --user daemon-reload
systemctl --user start yoitsu-pod.service yoitsu-pasloe.service yoitsu-trenni.service
```

Quadlet-generated services are transient. Keep the source files under the user
Quadlet search path and let the generator apply their `[Install]` metadata on
`daemon-reload`.

## Operations

Status:

```bash
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
  the wrappers recopy the source tree and reinstall the packages.
- The component repo mounts are read-only; mutable runtime state is kept in named volumes.
- `pasloe` is isolated in its own container so event storage stays up even if the job-running side is unstable.
- `palimpsest` is intentionally not a third long-lived container. Trenni launches it as short-lived subprocesses so the current supervisor/job model remains intact.
- If we later re-enable `bubblewrap`, do it as an explicit follow-up decision with
  a container-path model and a tested security policy, not as a default toggle.
