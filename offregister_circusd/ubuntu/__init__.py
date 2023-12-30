from fabric.operations import _run_command
from offregister_fab_utils.apt import apt_depends
from offregister_fab_utils.ubuntu.systemd import restart_systemd

from offregister_circusd.utils import _install_backend, _setup_circus


def install0(c, *args, **kwargs):
    apt_depends("libpcre3", "libpcre3-dev")
    # ^ Needed for uWSGI

    # if not exists("/etc/systemd/system/circusd.service"):
    use_sudo = kwargs.get("use_sudo", True)
    remote_user = kwargs.get(
        "SERVICE_USER", _run_command("echo $USER", quiet=True, sudo=use_sudo)
    )
    if remote_user.startswith("$"):
        remote_user = _run_command(
            "echo {remote_user}".format(remote_user=remote_user),
            quiet=True,
            sudo=use_sudo,
        )

    database_uri = kwargs.get("BACKEND_DATABASE_URI", kwargs["RDBMS_URI"])
    if not isinstance(database_uri, str):
        database_uri = "".join(map(str, database_uri))
    name = kwargs["GIT_REPO"][kwargs["GIT_REPO"].rfind("/") + 1 :].replace("-", "_")
    env_vars = "\n{}".format(
        "\n".join(
            "{key}={val}".format(
                key=key,
                val="".join(map(str, val)) if isinstance(val, (list, tuple)) else val,
            )
            for key, val in kwargs.get("BACKEND_ENV_VARS", {}).items()
        )
    )
    _install_backend(
        backend_root=kwargs["BACKEND_ROOT"],
        name=name,
        remote_user=remote_user,
        backend_virtual_env=kwargs["BACKEND_VIRTUAL_ENV"],
        team=kwargs["GIT_TEAM"],
        repo=kwargs["GIT_REPO"],
        database_uri=database_uri,
        env_vars="Environment='".join(env_vars),
    )
    _setup_circus(
        home=_run_command("echo $HOME", quiet=True, sudo=use_sudo),
        name=name,
        remote_user=remote_user,
        circus_virtual_env=kwargs.get("CIRCUS_VIRTUALENV", "/opt/venvs/circus"),
        backend_virtual_env=kwargs["BACKEND_VIRTUAL_ENV"],
        database_uri=database_uri,
        env_vars=env_vars,
        backend_root=kwargs["BACKEND_ROOT"],
        backend_logs_root=kwargs["BACKEND_LOGS_ROOT"],
        port=int(kwargs.get("BACKEND_PORT", "8001")),
    )
    return restart_systemd("circusd")
