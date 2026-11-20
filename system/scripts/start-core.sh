#!/usr/bin/env bash
# Lance neronOS Core depuis ce clone (dev / test hors systemd).
# Raccourci de start-module.sh core : voir ce script pour les options.
exec "$(dirname "${BASH_SOURCE[0]}")/start-module.sh" core
