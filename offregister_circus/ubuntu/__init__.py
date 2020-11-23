from fabric.api import run
from fabric.contrib.files import exists
from fabric.operations import _run_command

from offregister_fab_utils.apt import apt_depends
from offregister_fab_utils.ubuntu.systemd import restart_systemd
from offregister_circus.utils import _install_backend, _setup_circus


def install0(*args, **kwargs):
    apt_depends("python3-dev")

    use_sudo = kwargs.get("use_sudo", True)
    remote_user = kwargs.get(
        "SERVICE_USER", "root" if use_sudo else run("echo $USER", quiet=True)
    )

    if not exists("/etc/systemd/system/circusd.service"):
        _install_backend(
            backend_root=kwargs["BACKEND_ROOT"],
            remote_user=remote_user,
            backend_virtual_env=kwargs["BACKEND_VIRTUAL_ENV"],
            team=kwargs["GIT_TEAM"],
            repo=kwargs["GIT_REPO"],
            database_uri=kwargs["BACKEND_DATABASE_URI"],
        )
        _setup_circus(
            home=_run_command("echo $HOME", quiet=True, sudo=use_sudo),
            name=kwargs["GIT_REPO"][kwargs["GIT_REPO"].rfind("/") + 1 :],
            remote_user=remote_user,
            circus_virtual_env=kwargs.get("CIRCUS_VIRTUALENV", "/opt/venvs/circus"),
            backend_virtual_env=kwargs["BACKEND_VIRTUAL_ENV"],
            database_uri=kwargs["BACKEND_DATABASE_URI"],
            backend_root=kwargs["BACKEND_ROOT"],
        )
        return restart_systemd("circusd")
