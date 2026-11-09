#!/usr/bin/env bash
# Cloudflare WARP (free VPN) in local-proxy mode on a GitHub runner.
# Only Zillow traffic goes through it (socks5://127.0.0.1:40000); GitHub/Google traffic stays direct.
#   bash cloud/warp.sh install   -> install + connect
#   bash cloud/warp.sh rotate    -> drop the WARP identity and register a new one (usually a new exit IP)
set -u
W="warp-cli --accept-tos"
connect() {
  $W registration new >/dev/null 2>&1 || true
  $W mode proxy >/dev/null 2>&1 || $W set-mode proxy >/dev/null 2>&1 || true
  $W proxy port 40000 >/dev/null 2>&1 || $W set-proxy-port 40000 >/dev/null 2>&1 || true
  $W connect >/dev/null 2>&1 || true
  for i in $(seq 1 20); do
    ip=$(curl -s -m 8 --socks5-hostname 127.0.0.1:40000 https://api.ipify.org || true)
    if [ -n "$ip" ]; then echo "WARP connected, exit IP: $ip"; return 0; fi
    sleep 2
  done
  echo "WARP did not come up"; return 1
}
case "${1:-install}" in
  install)
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y -qq cloudflare-warp >/dev/null
    sudo systemctl start warp-svc 2>/dev/null || true
    sleep 3
    connect ;;
  rotate)
    $W disconnect >/dev/null 2>&1 || true
    $W registration delete >/dev/null 2>&1 || true
    sleep 2
    connect ;;
esac
