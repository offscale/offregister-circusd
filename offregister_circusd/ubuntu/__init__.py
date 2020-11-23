from fabric.api import run
from fabric.contrib.files import exists
from fabric.operations import _run_command

from offregister_fab_utils.apt import apt_depends
from offregister_fab_utils.ubuntu.systemd import restart_systemd
from offregister_circusd.utils import _install_backend, _setup_circus


def install0(*args, **kwargs):
    if not exists("/etc/systemd/system/circusd.service"):
        use_sudo = kwargs.get("use_sudo", True)
        remote_user = kwargs.get(
            "SERVICE_USER", "root" if use_sudo else run("echo $USER", quiet=True)
        )

        database_uri = kwargs.get("BACKEND_DATABASE_URI", kwargs["RDBMS_URI"])
        if not isinstance(database_uri, str):
            database_uri = "".join(map(str, database_uri))
        _install_backend(
            backend_root=kwargs["BACKEND_ROOT"],
            remote_user=remote_user,
            backend_virtual_env=kwargs["BACKEND_VIRTUAL_ENV"],
            team=kwargs["GIT_TEAM"],
            repo=kwargs["GIT_REPO"],
            database_uri=database_uri,
        )
        _setup_circus(
            home=_run_command("echo $HOME", quiet=True, sudo=use_sudo),
            name=kwargs["GIT_REPO"][kwargs["GIT_REPO"].rfind("/") + 1 :],
            remote_user=remote_user,
            circus_virtual_env=kwargs.get("CIRCUS_VIRTUALENV", "/opt/venvs/circus"),
            backend_virtual_env=kwargs["BACKEND_VIRTUAL_ENV"],
            database_uri=database_uri,
            backend_root=kwargs["BACKEND_ROOT"],
        )
        return restart_systemd("circusd")
