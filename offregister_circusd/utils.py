from functools import partial
from os import path
from urllib.parse import urlparse

import offregister_python.ubuntu as offregister_python_ubuntu
from fabric.api import run, shell_env
from fabric.contrib.files import upload_template, exists
from fabric.operations import sudo, _run_command
from offregister_fab_utils.fs import cmd_avail
from offregister_fab_utils.git import clone_or_update
from offregister_fab_utils.misc import get_user_group_tuples
from offregister_fab_utils.ubuntu.systemd import restart_systemd
from offregister_postgres import ubuntu as postgres
from pkg_resources import resource_filename

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
        virtual_env=backend_virtual_env, python3=True, packages=("gunicorn", "uwsgi")
    )
    offregister_python_ubuntu.install_package1(
        package_directory=backend_root, virtual_env=backend_virtual_env
    )

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

    uwsgi_service = "/etc/systemd/system/{name}-uwsgi.service".format(name=name)
    upload_template(
        circus_dir("uwsgi.service"),
        uwsgi_service,
        context={
            "USER": user,
            "GROUP": group,
            "PORT": 8001,
            "{}_BACK".format(name.upper()): "{}/{}".format(backend_root, name),
            "UID": uid,
            "GID": gid,
            "VENV": backend_virtual_env,
            "BACKEND_ROOT": backend_root,
            "SERVICE_USER": "ubuntu",
            "NAME": name,
        },
        use_sudo=True,
        backup=False,
        mode=644,
    )
    grp = sudo("id -gn", quiet=True)
    sudo(
        "chown {grp}:{grp} {uwsgi_service}".format(grp=grp, uwsgi_service=uwsgi_service)
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
    backend_logs_root,
    port
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
            python3=True,
            virtual_env=circus_virtual_env,
        )
    else:
        run('python3 -m venv "{virtual_env}"'.format(virtual_env=circus_virtual_env))
    with shell_env(
        VIRTUAL_ENV=circus_virtual_env, PATH="{}/bin:$PATH".format(circus_virtual_env)
    ):
        run("pip install circus")
    conf_dir = "/etc/circus/conf.d"  # '/'.join((backend_root, 'config'))
    sudo(
        "mkdir -p {conf_dir} {backend_logs_root}".format(
            conf_dir=conf_dir, backend_logs_root=backend_logs_root
        )
    )
    py_ver = run(
        "{virtual_env}/bin/python --version".format(virtual_env=backend_virtual_env)
    ).partition(" ")[2][:3]
    sudo(
        "touch {backend_logs_root}/gunicorn.{{stderr,stdout}}.log".format(
            backend_logs_root=backend_logs_root
        )
    )
    upload_template(
        circus_dir("circus.ini"),
        "{conf_dir}/".format(conf_dir=conf_dir),
        context={
            "HOME": backend_logs_root,
            "BACKEND_LOGS_ROOT": backend_logs_root,
            "BACKEND_ROOT": backend_root,
            "NAME": name,
            "USER": remote_user,
            "VENV": backend_virtual_env,
            "PYTHON_VERSION": py_ver,
            "PORT": port,
        },
        backup=False,
        mode=644,
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
            backup=False,
            mode=644,
        )
    elif exists("/etc/systemd/system"):
        upload_template(
            circus_dir("circusd.service"),
            "/etc/systemd/system/",
            context=circusd_context,
            use_sudo=True,
            backup=False,
            mode=644,
        )
    else:
        upload_template(
            circus_dir("circusd.conf"),
            "/etc/init/",
            context=circusd_context,
            use_sudo=True,
            backup=False,
            mode=644,
        )
    return circus_virtual_env, database_uri
