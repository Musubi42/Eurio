ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPfTYL4Iic8xwkbF35hUq7uTUYzsXpjsdK1X5+oNYp1p Oim_M4

Côté PC (NixOS) — déclaratif

Dans ta configuration.nix (remplace raphael par ton user PC) :

{
  # SSH — key-only, ouvre le port 22 tout seul (openFirewall = true par défaut)
  services.openssh = {
    enable = true;
    settings.PasswordAuthentication = false;
    settings.PermitRootLogin = "no";
  };

  # Autorise la clé du Mac pour ton user
  users.users.raphael.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPfTYL4Iic8xwkbF35hUq7uTUYzsXpjsdK1X5+oNYp1p Oim_M4"
  ];

  # mDNS : rend `desktop.local` résolvable → pas d'IP en dur (survit au DHCP)
  services.avahi = {
    enable = true;
    publish = { enable = true; addresses = true; workstation = true; };
  };
}

Puis applique et récupère les infos dont j'ai besoin :

sudo nixos-rebuild switch
whoami                       # ton user PC (pour le ssh config Mac)
hostname                     # confirme que c'est bien "desktop"
ip -4 addr show | grep inet  # note l'IP LAN (192.168.x.x) au cas où mDNS traîne

## Infos récupérées (2026-07-03)

whoami   → raphael
hostname → desktop
IP LAN   → 192.168.1.163  (wlp6s0, /24, DHCP dynamique)