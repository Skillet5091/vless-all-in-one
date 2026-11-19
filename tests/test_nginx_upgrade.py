"""Exercise the real Bash upgrade functions without touching host services or repositories."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "vless-server.sh"
SOURCE = SCRIPT.read_text()
FUNCTIONS = SOURCE[SOURCE.index("_setup_nginx_official_repo() {"):SOURCE.index("EXTERNAL_LINKS_FILE=")]

MOCKS = r"""
set -o pipefail
check_cmd() {
    [[ "$1" == nginx && "${MOCK_NO_NGINX:-0}" == 1 ]] && return 1
    [[ "$1" == dnf && "${MOCK_USE_DNF:-1}" == 0 ]] && return 1
    if [[ "${MOCK_MISSING_TOOLS:-0}" == 1 && ! -f "$ROOT/tools-ready" ]]; then
        case "$1" in curl|gpg|openssl) return 1 ;; esac
    fi
    return 0
}
trace() { printf '%s\n' "$*" >> "$ROOT/commands"; }
_info() { printf 'INFO %s\n' "$*"; }
_ok() { printf 'OK %s\n' "$*"; }
_err() { printf 'ERROR %s\n' "$*"; }
_warn() { printf 'WARN %s\n' "$*"; }
nginx() {
    trace nginx "$@"
    case "$1" in
        -v) printf 'nginx version: nginx/%s (fixture)\n' "$(cat "$ROOT/version")" >&2 ;;
        -V) printf 'configure arguments: --prefix=%s/etc/nginx --with-compat\n' "$ROOT" >&2 ;;
        -T)
            [[ "${MOCK_MODULE_LOADED:-0}" == 1 ]] && printf 'load_module %s/modules/fixture.so;\n' "$ROOT"
            return 0 ;;
        -t)
            [[ "${MOCK_CONFIG_FAIL_BEFORE:-0}" == 1 && ! -e "$ROOT/upgraded" ]] && return 1
            [[ "${MOCK_CONFIG_FAIL_AFTER:-0}" == 1 && -e "$ROOT/upgraded" ]] && return 1
            return 0 ;;
    esac
}
svc() {
    trace svc "$@"
    case "$1" in
        status)
            [[ "${MOCK_STATUS_FAIL_AFTER:-0}" == 1 && -f "$ROOT/restarted" ]] && return 1
            [[ "$(cat "$ROOT/running")" == 1 ]] ;;
        restart)
            [[ "${MOCK_RESTART_FAIL:-0}" == 1 ]] && return 1
            touch "$ROOT/restarted"
            printf 1 > "$ROOT/running" ;;
        start) printf 1 > "$ROOT/running" ;;
        stop)
            [[ "${MOCK_STOP_FAIL:-0}" == 1 ]] && return 1
            printf 0 > "$ROOT/running" ;;
        *) return 1 ;;
    esac
}
curl() {
    trace curl "$@"
    [[ "${MOCK_DOWNLOAD_FAIL:-0}" == 1 ]] && return 22
    local out=""
    while [[ $# -gt 0 ]]; do
        [[ "$1" == -o ]] && { out="$2"; shift; }
        shift
    done
    printf 'official repository fixture\n' > "$out"
}
gpg() {
    trace gpg "$@"
    if [[ " $* " == *" --show-keys "* ]]; then
        if [[ "${MOCK_BAD_KEY:-0}" == 1 ]]; then
            printf 'fpr:::::::::0000000000000000000000000000000000000000:\n'
        else
            printf 'fpr:::::::::573BFD6B3D8FBC641079A6ABABF5BD827BD9BF62:\n'
        fi
    else
        [[ "${MOCK_DEARMOR_FAIL:-0}" == 1 ]] && return 1
        while [[ $# -gt 0 ]]; do
            [[ "$1" == --output ]] && { printf keyring > "$2"; return 0; }
            shift
        done
        return 1
    fi
}
openssl() {
    trace openssl "$@"
    if [[ "$1" == rsa ]]; then
        printf DER
    else
        cat >/dev/null
        if [[ "${MOCK_BAD_KEY:-0}" == 1 ]]; then
            printf 'SHA256(stdin)= invalid\n'
        else
            printf 'SHA256(stdin)= 03833138bf6288dcb545f7a154af24f5c63b94931fef6b078cd8061204a44327\n'
        fi
    fi
}
dpkg() {
    trace dpkg "$@"
    if [[ "$1" == --print-architecture ]]; then
        printf 'amd64\n'
    else
        command dpkg "$@"
    fi
}
dpkg-query() {
    trace dpkg-query "$@"
    if [[ "$1" == -S ]]; then
        printf '%s: %s\n' "${MOCK_MODULE_OWNER:-libnginx-mod-http-fixture}" "$2"
        return 0
    fi
    [[ "${MOCK_PACKAGE_QUERY_FAIL_AFTER:-0}" == 1 && -f "$ROOT/upgraded" ]] && return 1
    printf 'installed\t%s\n' "$(cat "$ROOT/package")"
}
rpm() {
    trace rpm "$@"
    case "$1" in
        --eval) printf 'x86_64\n' ;;
        --import) return 0 ;;
        -q) cat "$ROOT/package" ;;
        -qf) printf '%s' "${MOCK_MODULE_OWNER:-nginx-mod-http-fixture}" ;;
        *) return 1 ;;
    esac
}
mutate_package() {
    # Simulate maintainer scripts replacing config, removing links and starting the service.
    printf 'package nginx.conf\n' > "$ROOT/etc/nginx/nginx.conf"
    mkdir -p "$ROOT/etc/nginx/conf.d"
    printf 'server { listen 80; }\n' > "$ROOT/etc/nginx/conf.d/default.conf"
    command rm -f "$ROOT/etc/nginx/sites-enabled/example.conf"
    printf 1 > "$ROOT/running"
    [[ "${MOCK_INSTALL_FAIL:-0}" == 1 ]] && return 100
    if [[ "${MOCK_STALE_INSTALL:-0}" != 1 ]]; then
        printf '%s' "$TARGET_PACKAGE" > "$ROOT/package"
        [[ "${MOCK_WRONG_BINARY:-0}" == 1 ]] || printf '%s' "$TARGET_VERSION" > "$ROOT/version"
    fi
    touch "$ROOT/upgraded"
    return 0
}
apt-get() {
    trace apt-get "$@"
    case "$1" in
        update) [[ "${MOCK_REFRESH_FAIL:-0}" != 1 ]] ;;
        install)
            if [[ " $* " == *" nginx="* ]]; then
                mutate_package
            else
                touch "$ROOT/tools-ready"
            fi ;;
        *) return 1 ;;
    esac
}
apt-cache() {
    trace apt-cache "$@"
    [[ "${MOCK_LOOKUP_FAIL:-0}" == 1 ]] && return 1
    cat "$ROOT/available"
}
rpm_pm() {
    trace "$@"
    if [[ " $* " == *" makecache "* ]]; then
        [[ "${MOCK_REFRESH_FAIL:-0}" != 1 ]]
    elif [[ " $* " == *" list nginx "* ]]; then
        [[ "${MOCK_LOOKUP_FAIL:-0}" == 1 ]] && return 1
        cat "$ROOT/available"
    elif [[ " $* " == *" install "* && " $* " == *" nginx-"* ]]; then
        mutate_package
    elif [[ " $* " == *" install "* ]]; then
        touch "$ROOT/tools-ready"
    else
        return 1
    fi
}
dnf() { rpm_pm dnf "$@"; }
yum() { rpm_pm yum "$@"; }
apk() {
    trace apk "$@"
    case "$1" in
        --print-arch) printf 'x86_64\n' ;;
        update) [[ "${MOCK_REFRESH_FAIL:-0}" != 1 ]] ;;
        policy)
            [[ "${MOCK_LOOKUP_FAIL:-0}" == 1 ]] && return 1
            cat "$ROOT/available" ;;
        info)
            if [[ "$2" == --who-owns ]]; then
                printf '%s is owned by %s\n' "$3" "${MOCK_MODULE_OWNER:-nginx-mod-http-fixture}"
            elif [[ "$2" == --installed && "$3" == --verbose ]]; then
                printf 'nginx-%s\n' "$(cat "$ROOT/package")"
            else
                printf 'nginx: HTTP and reverse proxy server\n'
            fi ;;
        add)
            if [[ " $* " == *" nginx@vless_nginx "* ]]; then
                mutate_package
            else
                touch "$ROOT/tools-ready"
            fi ;;
        *) return 1 ;;
    esac
}
cp() {
    [[ "${MOCK_BACKUP_FAIL:-0}" == 1 && "$*" == *nginx-config ]] && return 1
    [[ "${MOCK_RESTORE_FAIL:-0}" == 1 && "$*" == *restore.*/nginx ]] && return 1
    command cp "$@"
}
"""


class NginxUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nginx-upgrade-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("etc/nginx/sites-available", "etc/nginx/sites-enabled", "etc/apk", "tmp", "modules"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        config = self.root / "etc/nginx/nginx.conf"
        config.write_text("# existing config\ninclude sites-enabled/*;\n")
        config.chmod(0o640)
        site = self.root / "etc/nginx/sites-available/example.conf"
        site.write_text("server { listen 2096; server_name example.com; }\n")
        site.chmod(0o600)
        (self.root / "etc/nginx/sites-enabled/example.conf").symlink_to(site)
        (self.root / "subscription.info").write_text("sub_port=2096\nsub_domain=example.com\n")
        self.original = self.snapshot()
        (self.root / "modules/fixture.so").write_bytes(b"module fixture")
        self.prepare()

    def snapshot(self):
        directory = self.root / "etc/nginx"
        snapshot = {".": directory.stat().st_mode & 0o777}
        for path in sorted(directory.rglob("*")):
            name = str(path.relative_to(directory))
            if path.is_symlink():
                snapshot[name] = ("link", os.readlink(path))
            elif path.is_dir():
                snapshot[name] = ("directory", path.stat().st_mode & 0o777)
            else:
                snapshot[name] = (path.read_bytes(), path.stat().st_mode & 0o777)
        return snapshot

    def prepare(self, distro="ubuntu", channel="mainline", before="1.18.0", running=True):
        for marker in ("upgraded", "restarted", "tools-ready"):
            (self.root / marker).unlink(missing_ok=True)
        self.distro = distro
        self.channel = channel
        self.version = "1.29.10" if channel == "mainline" else "1.28.3"
        previous = "1.29.9" if channel == "mainline" else "1.28.2"
        repo_base = "https://nginx.org/packages" + ("/mainline" if channel == "mainline" else "")
        if distro == "centos":
            self.package = self.version + "-1.el9.ngx"
            old_package = before + "-1.el9"
            available = f"nginx.x86_64 {previous}-1.el9.ngx vless-nginx\nnginx.x86_64 {self.package} vless-nginx\n"
        elif distro == "alpine":
            self.package = self.version + "-r1"
            old_package = before + "-r1"
            available = f"nginx policy:\n  {previous}-r1:\n    {repo_base}/alpine/v3.22/main\n  {self.package}:\n    {repo_base}/alpine/v3.22/main\n  99.0.0-r1:\n    https://dl-cdn.alpinelinux.org/alpine/v3.22/main\n"
        else:
            codename = "jammy" if distro == "ubuntu" else "bookworm"
            self.package = self.version + "-1~" + codename
            old_package = before + "-1~" + codename
            # Unsorted official versions and a higher non-official version test source filtering.
            available = f"nginx | {self.package} | {repo_base}/{distro} {codename}/nginx amd64 Packages\nnginx | 1.29.9-1~{codename} | {repo_base}/{distro} {codename}/nginx amd64 Packages\nnginx | 99.0.0-1 | https://mirror.example.com/{distro} {codename}/main amd64 Packages\n"
            if channel == "stable":
                available = f"nginx | {self.package} | {repo_base}/{distro} {codename}/nginx amd64 Packages\nnginx | 1.29.10-1~{codename} | https://nginx.org/packages/mainline/{distro} {codename}/nginx amd64 Packages\n"
        for file, value in (("version", before), ("package", old_package), ("running", str(int(running))), ("available", available)):
            (self.root / file).write_text(value)
        (self.root / "etc/os-release").write_text('VERSION_ID="9.5"\nVERSION_CODENAME="' + ("jammy" if distro == "ubuntu" else "bookworm") + '"\n')
        (self.root / "etc/alpine-release").write_text("3.22.1\n")
        (self.root / "etc/apk/repositories").write_text("https://dl-cdn.alpinelinux.org/alpine/v3.22/main\n")

    def run_upgrade(self, **flags):
        (self.root / "commands").write_text("")
        functions = FUNCTIONS.replace("/etc/", str(self.root / "etc") + "/")
        functions = functions.replace("/usr/share/keyrings", str(self.root / "usr/share/keyrings"))
        functions = functions.replace("/tmp/vless-nginx-upgrade.", str(self.root / "tmp/vless-nginx-upgrade."))
        functions = functions.replace("/var/cache/nginx", str(self.root / "var/cache/nginx"))
        env = {**os.environ, "ROOT": str(self.root), "DISTRO": self.distro,
               "VLESS_NGINX_CHANNEL": self.channel, "TARGET_PACKAGE": self.package,
               "TARGET_VERSION": self.version, "CURL_TIMEOUT_NORMAL": "10", "CURL_TIMEOUT_DOWNLOAD": "60",
               **{key: str(value) for key, value in flags.items()}}
        result = subprocess.run(["bash", "-c", MOCKS + functions + "\nupgrade_nginx_security\n"],
                                env=env, text=True, capture_output=True, timeout=15)
        self.output = result.stdout + result.stderr
        self.commands = (self.root / "commands").read_text() if (self.root / "commands").exists() else ""
        return result.returncode

    def assert_preserved(self):
        self.assertEqual(self.snapshot(), self.original)
        self.assertEqual((self.root / "subscription.info").read_text(), "sub_port=2096\nsub_domain=example.com\n")

    def assert_failed(self, **flags):
        self.assertNotEqual(self.run_upgrade(**flags), 0, self.output)
        self.assertNotIn("官方升级完成", self.output)

    def test_ubuntu_uses_official_latest_and_restarts_new_binary(self):
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertIn("nginx=" + self.package, self.commands)
        self.assertIn("--force-confold", self.commands)
        self.assertIn("APT::Update::Error-Mode=any", self.commands)
        self.assertIn("svc restart nginx", self.commands)
        self.assertLess(self.commands.index("svc stop nginx"), self.commands.index("apt-get install"))
        self.assertNotIn("svc reload", self.commands)
        self.assertIn("https://nginx.org/packages/mainline/ubuntu jammy nginx", (self.root / "etc/apt/sources.list.d/vless-nginx.list").read_text())
        self.assertIn("Pin-Priority: 900", (self.root / "etc/apt/preferences.d/vless-nginx").read_text())
        self.assertEqual((self.root / "version").read_text(), self.version)
        self.assert_preserved()
        self.assertFalse(list((self.root / "tmp").iterdir()))

    def test_debian_codename(self):
        self.prepare(distro="debian")
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertIn("mainline/debian bookworm nginx", (self.root / "etc/apt/sources.list.d/vless-nginx.list").read_text())
        self.assert_preserved()

    def test_stable_filters_out_mainline_packages(self):
        self.prepare(channel="stable")
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertIn("nginx=1.28.3-1~jammy", self.commands)
        self.assertNotIn("/mainline/", (self.root / "etc/apt/sources.list.d/vless-nginx.list").read_text())

    def test_rhel_dnf_and_yum(self):
        for use_dnf in (1, 0):
            with self.subTest(use_dnf=use_dnf):
                self.prepare(distro="centos")
                self.assertEqual(self.run_upgrade(MOCK_USE_DNF=use_dnf), 0, self.output)
                repo = (self.root / "etc/yum.repos.d/vless-nginx.repo").read_text()
                self.assertIn("mainline/centos/9/x86_64", repo)
                self.assertIn("gpgcheck=1", repo)
                self.assertIn("module_hotfixes=true", repo)
                self.assertIn(("dnf" if use_dnf else "yum") + " --enablerepo=vless-nginx", self.commands)
                self.assert_preserved()

    def test_alpine_tag_and_idempotent_repository(self):
        self.prepare(distro="alpine")
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertIn("apk add --upgrade nginx@vless_nginx", self.commands)
        self.assertTrue((self.root / "var/cache/nginx").is_dir())
        self.assert_preserved()
        self.assertEqual(self.run_upgrade(), 0, self.output)
        repositories = (self.root / "etc/apk/repositories").read_text()
        self.assertEqual(repositories.count("@vless_nginx"), 1)
        self.assertIn("已是官方", self.output)

    def test_stopped_service_stays_stopped(self):
        self.prepare(running=False)
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertEqual((self.root / "running").read_text(), "0")
        self.assertIn("svc stop nginx", self.commands)
        self.assertNotIn("svc restart nginx", self.commands)
        self.assert_preserved()

    def test_latest_is_a_noop(self):
        (self.root / "version").write_text(self.version)
        (self.root / "package").write_text(self.package)
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertIn("已是官方", self.output)
        self.assertNotIn("apt-get install", self.commands)
        self.assertNotIn("svc restart", self.commands)

    def test_no_downgrade(self):
        self.prepare(channel="stable", before="1.31.0")
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertIn("不执行降级", self.output)
        self.assertNotIn("apt-get install", self.commands)

    def test_newer_package_revision_is_not_downgraded(self):
        (self.root / "version").write_text(self.version)
        (self.root / "package").write_text(self.version + "-9~jammy")
        self.assertEqual(self.run_upgrade(), 0, self.output)
        self.assertIn("未执行降级", self.output)
        self.assertNotIn("apt-get install", self.commands)

    def test_missing_nginx_is_skipped(self):
        self.assertEqual(self.run_upgrade(MOCK_NO_NGINX=1), 0, self.output)
        self.assertEqual(self.commands, "")

    def test_prerequisites_are_installed_when_missing(self):
        self.assertEqual(self.run_upgrade(MOCK_MISSING_TOOLS=1), 0, self.output)
        self.assertIn("curl ca-certificates gnupg", self.commands)

    def test_invalid_channel_and_unsupported_distro(self):
        for field, value in (("channel", "invalid"), ("distro", "unsupported")):
            with self.subTest(field=field):
                setattr(self, field, value)
                self.assert_failed()
                self.assertNotIn("curl ", self.commands)
                setattr(self, field, "mainline" if field == "channel" else "ubuntu")

    def test_existing_invalid_config_stops_before_download(self):
        self.assert_failed(MOCK_CONFIG_FAIL_BEFORE=1)
        self.assertNotIn("curl ", self.commands)
        self.assert_preserved()

    def test_shadowed_binary_is_not_reported_as_latest(self):
        (self.root / "package").write_text(self.package)
        self.assert_failed()
        self.assertIn("命令与软件包版本不一致", self.output)
        self.assertNotIn("apt-get install", self.commands)

    def test_incompatible_modules_stop_before_repository_or_package_changes(self):
        for distro in ("ubuntu", "centos", "alpine"):
            with self.subTest(distro=distro):
                self.prepare(distro=distro)
                self.assert_failed(MOCK_MODULE_LOADED=1)
                self.assertIn("需先准备匹配新版的模块", self.output)
                self.assertNotIn("curl ", self.commands)
                self.assert_preserved()

    def test_official_modules_allow_upgrade(self):
        for distro in ("ubuntu", "centos", "alpine"):
            with self.subTest(distro=distro):
                self.prepare(distro=distro)
                self.assertEqual(self.run_upgrade(MOCK_MODULE_LOADED=1, MOCK_MODULE_OWNER="nginx-module-fixture"), 0, self.output)
                self.assert_preserved()

    def test_repository_download_and_key_failures(self):
        for flag in ("MOCK_DOWNLOAD_FAIL", "MOCK_BAD_KEY", "MOCK_DEARMOR_FAIL"):
            with self.subTest(flag=flag):
                self.assert_failed(**{flag: 1})
                self.assertNotIn("apt-get install", self.commands)
                self.assert_preserved()

    def test_alpine_rejects_wrong_signing_key(self):
        self.prepare(distro="alpine")
        self.assert_failed(MOCK_BAD_KEY=1)
        self.assertNotIn("apk add --upgrade", self.commands)

    def test_refresh_failures_stop_all_package_managers(self):
        for distro in ("ubuntu", "centos", "alpine"):
            with self.subTest(distro=distro):
                self.prepare(distro=distro)
                self.assert_failed(MOCK_REFRESH_FAIL=1)
                self.assertNotIn("--best install", self.commands)
                self.assertNotIn("apk add --upgrade", self.commands)
                self.assertNotIn("apt-get install", self.commands)
                self.assert_preserved()

    def test_version_lookup_failure(self):
        self.assert_failed(MOCK_LOOKUP_FAIL=1)
        self.assertNotIn("apt-get install", self.commands)

    def test_no_fallback_to_distribution_packages(self):
        (self.root / "available").write_text("nginx | 1.18.0-1 | https://mirror.example.com/ubuntu jammy/main amd64 Packages\n")
        self.assert_failed()
        self.assertNotIn("apt-get install", self.commands)

    def test_failed_install_restores_config_and_keeps_backup(self):
        self.assert_failed(MOCK_INSTALL_FAIL=1)
        self.assertIn("软件包升级失败", self.output)
        self.assert_preserved()
        self.assertTrue(list((self.root / "tmp").glob("*/nginx-config/nginx.conf")))

    def test_successful_command_with_stale_or_wrong_binary_is_failure(self):
        for flag in ("MOCK_STALE_INSTALL", "MOCK_WRONG_BINARY"):
            with self.subTest(flag=flag):
                self.prepare()
                self.assert_failed(**{flag: 1})
                self.assertIn("未达到官方候选版本", self.output)
                self.assertNotIn("svc restart nginx", self.commands)
                self.assert_preserved()

    def test_incompatible_new_config_does_not_restart(self):
        self.assert_failed(MOCK_CONFIG_FAIL_AFTER=1)
        self.assertIn("与现有配置/模块不兼容", self.output)
        self.assertNotIn("svc restart nginx", self.commands)
        self.assert_preserved()

    def test_restart_and_status_errors_are_not_suppressed(self):
        for flag in ("MOCK_RESTART_FAIL", "MOCK_STATUS_FAIL_AFTER"):
            with self.subTest(flag=flag):
                self.prepare()
                self.assert_failed(**{flag: 1})
                self.assertIn("启动失败", self.output)
                self.assert_preserved()

    def test_stop_failure_is_failure(self):
        self.prepare(running=False)
        self.assert_failed(MOCK_STOP_FAIL=1)
        self.assertIn("无法恢复 Nginx 停止状态", self.output)

    def test_active_service_stop_failure_does_not_install_packages(self):
        self.assert_failed(MOCK_STOP_FAIL=1)
        self.assertIn("停止旧版 Nginx 失败", self.output)
        self.assertNotIn("apt-get install", self.commands)
        self.assert_preserved()

    def test_backup_failure_stops_before_install(self):
        self.assert_failed(MOCK_BACKUP_FAIL=1)
        self.assertNotIn("apt-get install", self.commands)
        self.assert_preserved()

    def test_restore_failure_keeps_original_backup(self):
        self.assert_failed(MOCK_RESTORE_FAIL=1)
        self.assertIn("配置恢复失败", self.output)
        self.assertTrue(list((self.root / "tmp").glob("*/nginx-config/nginx.conf")))

    def test_installed_version_query_error_is_reported(self):
        self.assert_failed(MOCK_PACKAGE_QUERY_FAIL_AFTER=1)
        self.assertIn("读取新版 Nginx 软件包版本失败", self.output)
        self.assert_preserved()


if __name__ == "__main__":
    unittest.main()
