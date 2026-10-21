#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${ROOT_DIR}/vendor/rogue5.4"
BIN_DIR="${ROOT_DIR}/bin"

mkdir -p "${ROOT_DIR}/vendor" "${BIN_DIR}"

if [ ! -d "${VENDOR_DIR}/.git" ]; then
    echo "[build_terminal_rogue] Cloning Rogue 5.4.4 (Roguelike Restoration Project, BSD-3-Clause)..."
    git clone --depth 1 https://github.com/RoguelikeRestorationProject/rogue5.4.git "${VENDOR_DIR}"
fi

cd "${VENDOR_DIR}"

# Patch opaque ncurses 6 struct accesses for modern Linux toolchains
sed -i 's/curscr->_cury = oy;/wmove(curscr, oy, ox);/g' main.c
sed -i 's/curscr->_curx = ox;//g' main.c
sed -i 's/if (cur_term->type.Strings == NULL)/if (0)/g' mdport.c

if [ ! -f Makefile ]; then
    echo "[build_terminal_rogue] Running ./configure..."
    CFLAGS="-O2 -std=gnu89 -Wno-error" ./configure --enable-scorefile="${BIN_DIR}/rogue54.scr" --enable-lockfile="${BIN_DIR}/rogue54.lck"
fi

echo "[build_terminal_rogue] Compiling rogue..."
make CFLAGS="-O2 -std=gnu89 -Wno-error"

cp -f rogue "${BIN_DIR}/rogue"
chmod +x "${BIN_DIR}/rogue"
echo "[build_terminal_rogue] Successfully built Terminal Rogue 5.4.4 at: ${BIN_DIR}/rogue"
