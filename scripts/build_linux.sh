#!/usr/bin/env bash
# Build the OpenCycleTrainer Flatpak bundle with one command.
#
# Fetches what it needs (uv, Python, the Flatpak runtime, SDK and PySide base app, and
# flatpak-builder if it is not installed) without root, brings the locked dependencies
# up to date, runs the tests, generates the Flatpak's offline Python sources from
# uv.lock, and builds the app. Only flatpak, curl and an internet connection are required.
#
# Output: dist/OpenCycleTrainer-<version>-<arch>.flatpak
set -euo pipefail

readonly PYTHON_VERSION="3.13"
readonly UV_VERSION="0.13.7"
readonly UV_WHEEL_URL_X86_64="https://files.pythonhosted.org/packages/b9/93/0e053a2ca4523ee9825ccbedeb7121470d0a188933f11688b6d90d7f5c08/uv-0.13.7-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
readonly UV_WHEEL_SHA256_X86_64="2c9bdc4a872b60a93c5f26c0791089ea11585a4f9d3b3c017d78eb8487505e25"
readonly UV_WHEEL_URL_AARCH64="https://files.pythonhosted.org/packages/96/72/da1119f94034d7173e6c8e2cd77a6299744458f0af3cb8e3a04d5cd419d1/uv-0.13.7-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl"
readonly UV_WHEEL_SHA256_AARCH64="a90f5d95716ab83091f0f73a8e7ec64e557abf2a28537fcd719b2ac88e6f725a"
readonly APP_NAME="OpenCycleTrainer"
readonly APP_ID="org.opencycletrainer.OpenCycleTrainer"
readonly FLATHUB_REMOTE="flathub"
readonly FLATHUB_REPO_URL="https://dl.flathub.org/repo/flathub.flatpakrepo"
readonly FLATPAK_BUILDER_APP="org.flatpak.Builder"
# Python packages the io.qt.PySide.BaseApp base already ships inside the Flatpak.
readonly BASE_APP_PROVIDES=(pyside6)
readonly VERSION_SCRIPT="import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
# Run inside the Flatpak SDK: describes its interpreter so wheels are chosen for it.
readonly SDK_TARGET_SCRIPT='
import json
try:
    from pip._vendor.packaging import markers, tags
except ImportError:
    from packaging import markers, tags
print(json.dumps({"environment": markers.default_environment(), "tags": [str(t) for t in tags.sys_tags()]}))
'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly MANIFEST="$REPO_ROOT/packaging/linux/$APP_ID.yaml"
readonly DEPS_CONVERTER="$REPO_ROOT/packaging/linux/flatpak_deps.py"
readonly BUILD_ROOT="$REPO_ROOT/build/linux"
readonly TOOLS_ROOT="$REPO_ROOT/build/tools"
readonly DIST_ROOT="$REPO_ROOT/dist"

usage() {
    cat <<EOF
Usage: scripts/build_linux.sh [--upgrade] [--skip-tests] [--install]

  --upgrade     Upgrade every dependency to the newest version pyproject.toml allows
                (rewrites uv.lock) and update the Flatpak runtime, SDK and base app.
  --skip-tests  Skip the test suite.
  --install     Also install the built bundle for the current user.
EOF
}

step() {
    printf '\n==> %s\n' "$*"
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

require() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' is required but was not found in PATH. $2"
}

# Print a top-level scalar from the Flatpak manifest, e.g. "runtime-version".
manifest_value() {
    local value
    value="$(sed -n -E "s/^$1:[[:space:]]*\"?([^\"[:space:]]+)\"?[[:space:]]*$/\1/p" "$MANIFEST" | head -n 1)"
    [[ -n "$value" ]] || die "Could not read '$1' from $MANIFEST."
    printf '%s\n' "$value"
}

# Print the path to uv: from PATH, or a pinned copy downloaded into build/tools.
find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return
    fi
    local url sha256
    case "$(uname -m)" in
        x86_64) url="$UV_WHEEL_URL_X86_64" sha256="$UV_WHEEL_SHA256_X86_64" ;;
        aarch64 | arm64) url="$UV_WHEEL_URL_AARCH64" sha256="$UV_WHEEL_SHA256_AARCH64" ;;
        *) die "No pinned uv download for $(uname -m); install uv (https://docs.astral.sh/uv/) and rerun." ;;
    esac
    local uv_dir="$TOOLS_ROOT/uv-$UV_VERSION"
    local uv_bin="$uv_dir/uv-$UV_VERSION.data/scripts/uv"
    if [[ ! -x "$uv_bin" ]]; then
        require curl "Install curl, or install uv yourself."
        local wheel="$TOOLS_ROOT/uv-$UV_VERSION.whl"
        mkdir -p "$TOOLS_ROOT"
        echo "Downloading $url" >&2
        curl --fail --location --silent --show-error --output "$wheel" "$url"
        if ! printf '%s  %s\n' "$sha256" "$wheel" | sha256sum --check --status; then
            rm -f "$wheel"
            die "Checksum mismatch for $url."
        fi
        rm -rf "$uv_dir"
        mkdir -p "$uv_dir"
        if command -v unzip >/dev/null 2>&1; then
            unzip -q "$wheel" -d "$uv_dir" >&2
        elif command -v python3 >/dev/null 2>&1; then
            python3 -m zipfile -e "$wheel" "$uv_dir"
        else
            die "Need unzip or python3 to unpack uv."
        fi
        rm -f "$wheel"
        chmod +x "$uv_bin"
    fi
    printf '%s\n' "$uv_bin"
}

upgrade=false
run_tests=true
install_bundle=false
while (($#)); do
    case "$1" in
        --upgrade) upgrade=true ;;
        --skip-tests) run_tests=false ;;
        --install) install_bundle=true ;;
        -h | --help) usage; exit 0 ;;
        *) usage >&2; die "Unknown option '$1'." ;;
    esac
    shift
done

require flatpak "Install it from your distribution's packages (see https://flatpak.org/setup/)."
cd "$REPO_ROOT"

# Keep the build's environment apart from any development .venv.
export UV_PROJECT_ENVIRONMENT="$BUILD_ROOT/venv"
export UV_PYTHON="$PYTHON_VERSION"
uv_bin="$(find_uv)"

step "Updating dependencies"
if $upgrade; then
    "$uv_bin" lock --upgrade
else
    "$uv_bin" lock
fi
"$uv_bin" sync --locked --extra dev

if $run_tests; then
    step "Running tests"
    "$uv_bin" run --no-sync python -m pytest
fi

version="$("$uv_bin" run --no-sync python -c "$VERSION_SCRIPT")"
arch="$(flatpak --default-arch)"
runtime_version="$(manifest_value runtime-version)"
sdk_ref="$(manifest_value sdk)//$runtime_version"
flatpak_refs=(
    "$(manifest_value runtime)//$runtime_version"
    "$sdk_ref"
    "$(manifest_value base)//$(manifest_value base-version)"
)

step "Installing the Flatpak runtime, SDK and base app"
flatpak remote-add --user --if-not-exists "$FLATHUB_REMOTE" "$FLATHUB_REPO_URL"
if command -v flatpak-builder >/dev/null 2>&1; then
    builder=(flatpak-builder)
else
    flatpak_refs+=("$FLATPAK_BUILDER_APP")
    builder=(flatpak run "$FLATPAK_BUILDER_APP")
fi
missing_refs=()
for ref in "${flatpak_refs[@]}"; do
    flatpak info "$ref" >/dev/null 2>&1 || missing_refs+=("$ref")
done
if ((${#missing_refs[@]})); then
    flatpak install --user --noninteractive "$FLATHUB_REMOTE" "${missing_refs[@]}"
fi
if $upgrade; then
    flatpak update --noninteractive "${flatpak_refs[@]}"
fi

step "Generating the Flatpak's Python dependencies from uv.lock"
mkdir -p "$BUILD_ROOT"
flatpak run --command=python3 "$sdk_ref" -c "$SDK_TARGET_SCRIPT" >"$BUILD_ROOT/sdk-target.json"
exclude_args=()
for package in "${BASE_APP_PROVIDES[@]}"; do
    exclude_args+=(--exclude "$package")
done
"$uv_bin" run --no-sync python "$DEPS_CONVERTER" \
    --lock uv.lock \
    --target "$BUILD_ROOT/sdk-target.json" \
    "${exclude_args[@]}" \
    --output "$BUILD_ROOT/python-deps.json"

step "Building $APP_NAME $version for $arch"
rm -rf "$BUILD_ROOT/repo"
"${builder[@]}" \
    --force-clean \
    --state-dir="$BUILD_ROOT/state" \
    --repo="$BUILD_ROOT/repo" \
    "$BUILD_ROOT/app" \
    "$MANIFEST"

bundle="$DIST_ROOT/$APP_NAME-$version-$arch.flatpak"
mkdir -p "$DIST_ROOT"
flatpak build-bundle --runtime-repo="$FLATHUB_REPO_URL" "$BUILD_ROOT/repo" "$bundle" "$APP_ID"

if $install_bundle; then
    step "Installing $APP_ID for the current user"
    flatpak install --user --noninteractive --reinstall --bundle "$bundle"
fi

step "Flatpak bundle created at: $bundle"
