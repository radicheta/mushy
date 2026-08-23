<?php
# MUSHY-35 — delete the disabled legacy "Musguito VPN" OpenVPN server from pfSense.
# Its tls-auth key was published in this repo (commit 2d13277). The server is
# superseded by kernel WireGuard, which now owns the same 172.16.10.0/24.
#
# Run:  ssh admin@10.68.155.1 php < scripts/security/mushy35-delete-musguito.php
#
# Three guards below make this a no-op unless it is exactly the intended object.
# It will NOT touch the OpenVPN *client* (client2 -> vpnforest.ddns.net), which
# belongs to the VFX studio.

require_once("config.inc");
require_once("util.inc");
global $config;

$srv = &$config["openvpn"]["openvpn-server"];
if (!is_array($srv)) { echo "ABORT: no openvpn-server array\n"; exit(1); }

$idx = null;
foreach ($srv as $i => $s) if ((string)($s["vpnid"] ?? "") === "1") { $idx = $i; break; }
if ($idx === null)                                        { echo "ABORT: vpnid 1 not found\n"; exit(1); }
if (!isset($srv[$idx]["disable"]))                        { echo "ABORT: server is ENABLED, refusing\n"; exit(1); }
if (($srv[$idx]["tunnel_network"] ?? "") !== "172.16.10.0/24") { echo "ABORT: unexpected tunnel_network\n"; exit(1); }

printf("deleting vpnid=%s desc=%s port=%s tunnel=%s\n",
  $srv[$idx]["vpnid"], $srv[$idx]["description"], $srv[$idx]["local_port"], $srv[$idx]["tunnel_network"]);

unset($srv[$idx]);
$srv = array_values($srv);
write_config("MUSHY-35: delete disabled legacy Musguito VPN (leaked tls-auth key; superseded by wg0)");
echo "WROTE\n";
