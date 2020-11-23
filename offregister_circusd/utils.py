from urllib.parse import urlparse

from offregister_fab_utils.fs import cmd_avail
from offregister_fab_utils.misc import get_user_group_tuples

from functools import partial
from os import path

from offregister_fab_utils.ubuntu.systemd import restart_systemd
from pkg_resources import resource_filename

from fabric.api import run, shell_env
from fabric.contrib.files import upload_template, exists
from fabric.operations import sudo, _run_command

from offregister_fab_utils.git import clone_or_update
from offregister_postgres import ubuntu as postgres
import offregister_python.ubuntu as offregister_python_ubuntu

circus_dir = partial(
    path.join,
    path.dirname(resource_filename("offregister_circusd", "__init__.py")),
    "data",
)


def _install_backend(
    backend_root,
    remote_user,
    backend_virtual_env,
    team,
    repo,
    database_uri,
    install_postgres=True,
    create_postgres_database=True,
    use_sudo=True,
):
    name = repo[repo.rfind("/") + 1 :]
    uname = run("uname -v")
    is_ubuntu = "Ubuntu" in uname
    run_cmd = partial(_run_command, sudo=use_sudo)

    if install_postgres:
        if not is_ubuntu and not cmd_avail("psql"):
            raise NotImplementedError("Postgres install on {!r}".format(uname))
        postgres.install0()

    if create_postgres_database:
        parsed_database_uri = urlparse(database_uri)

        created = postgres.setup_users(
            create=(
                {
                    "user": parsed_database_uri.username,
                    "password": parsed_database_uri.password,
                    "dbname": parsed_database_uri.path[1:],
                },
            ),
            connection_str=database_uri,
        )
        assert created is not None

    clone_or_update(
        team=team, repo=repo, use_sudo=use_sudo, to_dir=backend_root, branch="master"
    )
    offregister_python_ubuntu.install_venv0(
        virtual_env=backend_virtual_env, python3=True
    )
    offregister_python_ubuntu.install_package1(
        package_directory=backend_root, virtual_env=backend_virtual_env
    )

    # UWSGI
    with shell_env(
        VIRTUAL_ENV=backend_virtual_env, PATH="{}/bin:$PATH".format(backend_virtual_env)
    ):
        run_cmd("pip3 install uwsgi")

    if not exists("/etc/systemd/system"):
        raise NotImplementedError("Non SystemD platforms")

    if run(
        "id {remote_user}".format(remote_user=remote_user), warn_only=True, quiet=True
    ).failed:
        sudo(
            'adduser {remote_user} --disabled-password --quiet --gecos ""'.format(
                remote_user=remote_user
            )
        )
    (uid, user), (gid, group) = get_user_group_tuples(remote_user)

    upload_template(
        circus_dir("uwsgi.service"),
        "/etc/systemd/system/{name}-uwsgi.service".format(name=name),
        context={
            "USER": user,
            "GROUP": group,
            "PORT": 8001,
            "{}_BACK".format(name.upper()): "{}/{}".format(backend_root, name),
            "UID": uid,
            "GID": gid,
            "VENV": backend_virtual_env,
        },
        use_sudo=True,
    )
    restart_systemd("{name}-uwsgi".format(name=name))

    return backend_virtual_env, database_uri

    # return _setup_circus(circus_virtual_env, database_uri, home, is_ubuntu, remote_user, backend_root, uname)


def _setup_circus(
    home,
    name,
    remote_user,
    circus_virtual_env,
    backend_virtual_env,
    database_uri,
    backend_root,
):
    sudo("mkdir -p {circus_virtual_env}".format(circus_virtual_env=circus_virtual_env))
    group_user = run(
        """printf '%s:%s' "$USER" $(id -gn)""", shell_escape=False, quiet=True
    )
    sudo(
        "chown -R {group_user} {circus_virtual_env}".format(
            group_user=group_user, circus_virtual_env=circus_virtual_env
        )
    )
    uname = run("uname -v", quiet=True)
    is_ubuntu = "Ubuntu" in uname
    if is_ubuntu:
        offregister_python_ubuntu.install_venv0(
            python3=True, virtual_env=circus_virtual_env
        )
    else:
        run('python3 -m venv "{virtual_env}"'.format(virtual_env=circus_virtual_env))
    with shell_env(
        VIRTUAL_ENV=circus_virtual_env, PATH="{}/bin:$PATH".format(circus_virtual_env)
    ):
        run("pip install circus")
    conf_dir = "/etc/circus/conf.d"  # '/'.join((backend_root, 'config'))
    sudo("mkdir -p {conf_dir}".format(conf_dir=conf_dir))
    py_ver = run(
        "{virtual_env}/bin/python --version".format(virtual_env=backend_virtual_env)
    ).partition(" ")[2][:3]
    upload_template(
        circus_dir("circus.ini"),
        "{conf_dir}/".format(conf_dir=conf_dir),
        context={
            "HOME": backend_root,
            "NAME": name,
            "USER": remote_user,
            "VENV": backend_virtual_env,
            "PYTHON_VERSION": py_ver,
        },
        use_sudo=True,
    )
    circusd_context = {
        "CIRCUS_VENV": circus_virtual_env,
        "CONF_DIR": conf_dir,
        "BACKEND_ROOT": backend_root,
        "NAME": name,
    }
    if uname.startswith("Darwin"):
        upload_template(
            circus_dir("circusd.launchd.xml"),
            "{home}/Library/LaunchAgents/io.readthedocs.circus.plist".format(home=home),
            context=circusd_context,
        )
    elif exists("/etc/systemd/system"):
        upload_template(
            circus_dir("circusd.service"),
            "/etc/systemd/system/",
            context=circusd_context,
            use_sudo=True,
        )
    else:
        upload_template(
            circus_dir("circusd.conf"),
            "/etc/init/",
            context=circusd_context,
            use_sudo=True,
        )
    return circus_virtual_env, database_uri
