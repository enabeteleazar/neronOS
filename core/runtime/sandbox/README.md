# Agent Sandbox V2

`AgentSandbox` exécute les tests et validations métier des agents générés.
Le backend est sélectionné par `NERON_SANDBOX_BACKEND` :

- `systemd` : backend strict, sans fallback ;
- `auto` : préfère systemd puis utilise le backend Python si le préflight échoue ;
- `python` : isolation par processus et audit Python.

## Élévation systemd

`NERON_SANDBOX_SYSTEMD_USE_SUDO` accepte `true`, `false` ou `auto`
(`auto` par défaut).

- `false` lance directement `/usr/bin/systemd-run` ;
- `true` lance uniquement `sudo -n /usr/bin/systemd-run` ;
- `auto` n’utilise pas sudo en root et utilise `sudo -n` pour un processus
  non-root.

Le Sandbox ne lance jamais un sudo interactif et ne demande jamais de mot de
passe. La règle sudoers doit rester limitée au binaire `systemd-run`.

En backend `systemd`, l’absence de systemd, du compte `neron-agent` ou du droit
sudo non interactif produit une erreur de préflight. En backend `auto`, la même
situation sélectionne le backend Python avec un `fallback_reason`.

## Diagnostics

`diagnostics()` et chaque résultat d’exécution exposent :

- `backend_selected` et l’alias compatible `backend_used` ;
- `systemd_run_path` et `systemd_available` ;
- `sudo_used`, `sudo_available` et `sudo_error` ;
- `fallback_reason` lorsqu’un backend de repli est utilisé ;
- `isolation_level` et la disponibilité du compte `neron-agent`.
