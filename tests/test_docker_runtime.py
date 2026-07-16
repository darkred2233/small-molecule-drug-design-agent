import pytest

from medagent.services.docker_runtime import (
    ContainerMount,
    DockerMountBuilder,
    DockerPathNotSharedError,
)


def test_named_volume_path_is_reused_without_host_bind(tmp_path):
    api_root = tmp_path / "api-local"
    builder = DockerMountBuilder(
        mounts=[
            ContainerMount(
                mount_type="volume",
                source="/var/lib/docker/volumes/medagent-local/_data",
                destination=api_root.as_posix(),
                name="medagent-local",
            )
        ],
        containerized=True,
    )

    input_path = builder.bind(api_root / "tool-runs" / "input.sdf", "/data/input.sdf")
    output_path = builder.bind(api_root / "tool-runs" / "output", "/data/output")

    assert input_path == "/medagent-volumes/medagent-local/tool-runs/input.sdf"
    assert output_path == "/medagent-volumes/medagent-local/tool-runs/output"
    assert builder.arguments == [
        "--mount",
        "type=volume,src=medagent-local,dst=/medagent-volumes/medagent-local",
    ]


def test_api_bind_mount_is_translated_back_to_host_source(tmp_path):
    api_root = tmp_path / "api-models"
    host_root = tmp_path / "host-models"
    builder = DockerMountBuilder(
        mounts=[
            ContainerMount(
                mount_type="bind",
                source=str(host_root),
                destination=api_root.as_posix(),
                read_write=False,
            )
        ],
        containerized=True,
    )

    container_path = builder.bind(api_root / "diffdock", "/models", read_only=True)

    assert container_path == "/models"
    assert builder.arguments == ["-v", f"{host_root / 'diffdock'}:/models:ro"]


def test_container_private_path_is_rejected(tmp_path):
    builder = DockerMountBuilder(mounts=[], containerized=True)

    with pytest.raises(DockerPathNotSharedError, match="private to the API container"):
        builder.bind(tmp_path / "private.sdf", "/data/private.sdf")
