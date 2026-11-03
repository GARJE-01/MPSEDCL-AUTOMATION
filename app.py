import streamlit as st
import pandas as pd
import ipaddress
import jinja2
import requests
import re
from datetime import datetime

st.set_page_config(page_title="MPSWAN Config Automation", layout="wide")

APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbwTOMwPX41Dd1_H1vzCRij7iS2CJnKABx8znesk7AaPrE-rQwwFtXq8OLlDQQIM3YQ/exec"

# Jinja2 Template fully parameterized for any subnet mask / prefix
JINJA_TEMPLATE_STRING = """=====
!! Take input from Excel/Email.:

Host Name = {{ host_name }}
Site Address = {{ site_address }}
Local contact Network eng = {{ local_contact }}

LSI No = {{ lsi_no }}
RA no = {{ ra_no }}

WAN IP PE end = {{ wan_pe_raw }}
WAN IP CPE = {{ wan_cpe_raw }}
LAN IP = {{ lan_raw }}

!! Calculate these from LAN Subnet 
{{ lan_first_ip }} - {{ lan_last_ip }}
{{ lan_broadcast_ip }} = broadcast
{{ lan_mask }}

=====
!! Router Console Access

Username: admin 
Password: admin 

Enter new Password: admin 
Confirm Password: admin 

Router# 

pnpa service discovery stop 

!! Wait for few minutes before doing the next commands:

config-transaction

hostname {{ host_name }}

interface GigabitEthernet 0/0/1
no vrf forwarding
!! Change IP Address & Subnet Mask
ip add {{ wan_cpe_ip }} {{ wan_mask }}
no shutdown
bandwidth {{ bandwidth_kbps }}
exit

ip domain name MPSEDCL 

!! LOCAL DB:

username airtel privilege 15 password Airtel@123
username cisco privilege 15 password cisco
enable password cisco
clock timezone IST 5 30
aaa new-model

aaa authentication login CONSOLE local 

line con 0
login authentication CONSOLE 
logging sync 
exit

line vty 0 4
 transport input telnet ssh
 login authentication CONSOLE 
 logging sync 
exit

line vty 5 80
 transport input telnet ssh
 login authentication CONSOLE 
 logging sync 
exit

!!!!

!! Change the Next-Hop of WAN-1
ip route 0.0.0.0 0.0.0.0 {{ wan_pe_ip }}

router bgp 65001
bgp log-neighbor-changes

!! Change the Neighbor to be WAN-1 Next-Hop
neighbor {{ wan_pe_ip }} remote-as 9730

address-family ipv4
redistribute connected
redistribute static

!! Change the Neighbor to be WAN-1 Next-Hop
neighbor {{ wan_pe_ip }} activate

!! Change the Neighbor to be WAN-1 Next-Hop
neighbor {{ wan_pe_ip }} allowas-in 6

exit
exit

interface Vlan1 
no vrf forwarding

!! LAN Subnet + 1, IP Address
ip add {{ lan_cpe_ip }} {{ lan_mask }}

no shut 
exit  

interface Gi 0/1/0
switchport mode access 
switchport access vlan 1
exit 

interface Gi 0/1/1
switchport mode access 
switchport access vlan 1
exit 

interface Gi 0/1/2
switchport mode access 
switchport access vlan 1
exit 

interface Gi 0/1/3
switchport mode access 
switchport access vlan 1
exit 

interface Gi 0/1/4
switchport mode access 
switchport access vlan 1
exit 

interface Gi 0/1/5
switchport mode access 
switchport access vlan 1
exit 

!! The IP present in Vlan-01
ip dhcp excluded-address {{ lan_cpe_ip }} {{ lan_cpe_ip }}

!! LAN - <Vlan-01 IP Address>
ip dhcp pool LAN-{{ lan_cpe_ip }}

!! LAN Network ID + Subnet Mask 
 network {{ lan_net_id }} {{ lan_mask }}

!! LAN - Vlan-01 IP Address
 default-router {{ lan_cpe_ip }}
exit 

snmp-server community swantulip RO
snmp-server host 10.124.4.126 version 2c swantulip

ip sla 1

!! WAN-1 Interface IP Address
icmp-jitter 10.124.4.47 source-ip {{ wan_cpe_ip }}

frequency 600
threshold 80
timeout 1000
ip sla schedule 1 life forever start-time now

commit
exit

crypto key gen rsa gen mod 2048

=====

show ip route 10.124.4.47

show ip bgp 10.124.4.47 

ping 10.124.4.47

!!

terminal len 0

show running-config 

show ip bgp sum 

show ip int br 

show vlan br 

show vrf 

show ip route connected 

show mac address-table dynamic 

show mac address-table static 

show ip arp | exc Incomplete

show version 

show platform 

show install summary 

show bootvar

show romvar

show inventory 

show clock detail

show vlan br

show ip ssh 

show crypto key my rsa

terminal no len 0

====
"""

def parse_bandwidth_kbps(bw_val):
    if pd.isna(bw_val) or not str(bw_val).strip():
        return 10000
    match = re.search(r"(\d+)", str(bw_val))
    return int(match.group(1)) * 1000 if match else 10000

def render_mpsedcl_config(data_dict):
    """
    Dynamically computes subnet masks, broadcast, usable ranges, 
    and network IDs for ANY CIDR prefix (/24, /25, /26, /27, /28, /29, /30, etc.)
    """
    wan_pe_raw = str(data_dict["wan_pe"]).strip()
    wan_cpe_raw = str(data_dict["wan_cpe"]).strip()
    lan_raw = str(data_dict["lan_ip"]).strip()

    # Default to /30 for WAN only if user omitted CIDR
    if "/" not in wan_pe_raw:
        wan_pe_raw += "/30"
    if "/" not in wan_cpe_raw:
        wan_cpe_raw += "/30"

    # Default to /24 for LAN only if user omitted CIDR
    if "/" not in lan_raw:
        lan_raw += "/24"

    wan_pe_iface = ipaddress.ip_interface(wan_pe_raw)
    wan_cpe_iface = ipaddress.ip_interface(wan_cpe_raw)

    # Dynamic network calculation for arbitrary prefixes
    lan_net = ipaddress.ip_network(lan_raw, strict=False)
    hosts = list(lan_net.hosts())

    if not hosts:
        raise ValueError(f"Invalid LAN subnet: {lan_raw} has no usable host addresses.")

    lan_first_ip = str(hosts[0])
    lan_last_ip = str(hosts[-1])
    lan_broadcast = str(lan_net.broadcast_address)
    lan_netmask = str(lan_net.netmask)
    lan_net_id = str(lan_net.network_address)

    context = {
        "host_name": str(data_dict["host_name"]).strip(),
        "site_address": str(data_dict.get("site_address", "")).strip(),
        "local_contact": str(data_dict.get("local_contact", "")).strip(),
        "lsi_no": str(data_dict.get("lsi_no", "")).strip(),
        "ra_no": str(data_dict.get("ra_no", "")).strip(),
        "wan_pe_raw": str(wan_pe_iface),
        "wan_cpe_raw": str(wan_cpe_iface),
        "wan_pe_ip": str(wan_pe_iface.ip),
        "wan_cpe_ip": str(wan_cpe_iface.ip),
        "wan_mask": str(wan_cpe_iface.netmask),
        "lan_raw": f"{lan_net_id}/{lan_net.prefixlen}",
        "lan_first_ip": lan_first_ip,
        "lan_last_ip": lan_last_ip,
        "lan_broadcast_ip": lan_broadcast,
        "lan_cpe_ip": lan_first_ip,
        "lan_net_id": lan_net_id,
        "lan_mask": lan_netmask,
        "bandwidth_kbps": parse_bandwidth_kbps(data_dict.get("bandwidth", 10)),
    }

    template = jinja2.Template(JINJA_TEMPLATE_STRING)
    return template.render(context), context

def push_to_online_sheet(payload):
    """Sends row details to Google Apps Script Webhook."""
    with st.spinner("Connecting and syncing to Google Sheet..."):
        try:
            clean_payload = {k: str(v).strip() for k, v in payload.items() if v is not None and str(v).strip() != ""}
            res = requests.post(APPS_SCRIPT_URL, json=clean_payload, timeout=20)
            if res.status_code == 200:
                try:
                    res_json = res.json()
                    if res_json.get("status") == "success":
                        st.success(f"✅ {res_json.get('message')}")
                    else:
                        st.error(f"⚠️ Sheet Error: {res_json.get('message')}")
                except ValueError:
                    st.success("✅ Data pushed successfully.")
            else:
                st.error(f"❌ Server Error ({res.status_code}): Could not communicate with sheet.")
        except Exception as err:
            st.error(f"❌ Connection Failed: {err}")

st.title("⚡ MPSWAN Site Automation & Config Generator")

uploaded_file = st.sidebar.file_uploader("Upload Site Master Sheet (.xlsx)", type=["xlsx"])
excel_path = uploaded_file if uploaded_file else "MPSWAN MPLS Link TN 654-2.xlsx"

try:
    df = pd.read_excel(excel_path, sheet_name="Sheet1")
except Exception as e:
    st.warning("Please ensure 'MPSWAN MPLS Link TN 654-2.xlsx' is present or upload it.")
    st.stop()

search_query = st.text_input("🔍 Search Site Address in Excel Sheet:", placeholder="e.g. VIJAYRAGHAVGARH, RAJNAGAR, ARON")

if search_query:
    matches = df[
        df["Site Address"].astype(str).str.contains(search_query, case=False, na=False) |
        df["Host Name"].astype(str).str.contains(search_query, case=False, na=False)
    ]

    if matches.empty:
        st.error("No matching Site Address found in Excel sheet.")
    else:
        def format_site_option(idx):
            addr = str(matches.loc[idx, "Site Address"]).strip()
            dist = str(matches.loc[idx, "Dist"]).strip()
            tehsil = str(matches.loc[idx, "Tehsil/Block"]).strip()
            return f"{addr}  |  Dist: {dist}  |  Block: {tehsil}"

        selected_idx = st.selectbox("Select Matching Site:", matches.index, format_func=format_site_option)
        row = matches.loc[selected_idx]

        site_address_val = str(row.get("Site Address", "")).replace("nan", "")
        dist_val = str(row.get("Dist", "")).replace("nan", "")
        tehsil_val = str(row.get("Tehsil/Block", "")).replace("nan", "")
        bw_val = str(row.get("Bandwidth (In Mbps)", "10 MBPS")).replace("nan", "10 MBPS")
        lsi_val = str(row.get("LSI No", "")).replace("nan", "")
        ra_val = str(row.get("RA no", "")).replace("nan", "")
        contact_val = str(row.get("Local contact Network eng", "")).replace("nan", "")

        excel_host = str(row.get("Host Name", "")).replace("nan", "")
        excel_wan_pe = str(row.get("WAN IP PE end", "")).replace("nan", "")
        excel_wan_cpe = str(row.get("WAN IP CPE\xa0", row.get("WAN IP CPE", ""))).replace("nan", "")
        excel_lan = str(row.get("LAN IP\xa0", row.get("LAN IP", ""))).replace("nan", "")

        st.markdown("---")
        st.subheader(f"Site Metadata from Excel: `{site_address_val}`")

        m1, m2, m3, m4 = st.columns(4)
        m1.info(f"**District:** {dist_val}")
        m2.info(f"**Tehsil/Block:** {tehsil_val}")
        m3.info(f"**Bandwidth:** {bw_val}")
        m4.info(f"**RA No:** {ra_val if ra_val else 'Pending'}")

        st.markdown("### ✍️ Customer-Provided Parameters")
        st.caption("Enter the exact prefix (e.g. /24, /26, /27, /28, /29, /30) provided by the customer:")

        col1, col2 = st.columns(2)
        with col1:
            in_hostname = st.text_input(
                "Host Name *",
                value=excel_host if excel_host else f"AIR_{site_address_val}".replace(" ", "_"),
                placeholder="e.g. AIR_IGRS_VIJAYRAGHAVGARH_KATNI",
                key=f"host_{selected_idx}"
            )
            in_lan = st.text_input(
                "LAN IP (with prefix/CIDR) *",
                value=excel_lan if excel_lan else "",
                placeholder="e.g. 172.17.3.248/29, 172.21.160.96/27, 10.101.7.0/25, 192.168.1.0/24",
                key=f"lan_{selected_idx}"
            )

        with col2:
            in_wan_pe = st.text_input(
                "WAN IP PE end *",
                value=excel_wan_pe if excel_wan_pe else "",
                placeholder="e.g. 172.49.232.209/30",
                key=f"wan_pe_{selected_idx}"
            )
            in_wan_cpe = st.text_input(
                "WAN IP CPE *",
                value=excel_wan_cpe if excel_wan_cpe else "",
                placeholder="e.g. 172.49.232.210/30",
                key=f"wan_cpe_{selected_idx}"
            )

        with st.expander("Local Contact / LSI Details (from Excel)"):
            in_contact = st.text_input("Local Contact Network Eng", value=contact_val, key=f"contact_{selected_idx}")
            in_lsi = st.text_input("LSI No", value=lsi_val, key=f"lsi_{selected_idx}")

        if not in_hostname or not in_wan_pe or not in_wan_cpe or not in_lan:
            st.warning("Please fill in all mandatory fields: Host Name, LAN IP, and WAN IPs.")
        else:
            site_data = {
                "host_name": in_hostname.strip(),
                "site_address": site_address_val,
                "local_contact": in_contact.strip(),
                "lsi_no": in_lsi.strip(),
                "ra_no": ra_val,
                "wan_pe": in_wan_pe.strip(),
                "wan_cpe": in_wan_cpe.strip(),
                "lan_ip": in_lan.strip(),
                "bandwidth": bw_val
            }

            try:
                cfg_out, ctx = render_mpsedcl_config(site_data)

                st.markdown("---")
                c_down, c_push = st.columns(2)
                with c_down:
                    st.download_button(
                        label="📥 Download Config (.txt)",
                        data=cfg_out,
                        file_name=f"mpsedcl_{ctx['host_name']}.txt",
                        mime="text/plain",
                        type="primary",
                        key=f"dl_btn_{selected_idx}"
                    )

                with c_push:
                    if st.button("🚀 Push / Update to Online Sheet", key=f"push_btn_{selected_idx}"):
                        payload = {
                            "host_name": ctx["host_name"],
                            "ra_no": ra_val,
                            "dist": dist_val,
                            "tehsil": tehsil_val,
                            "wan_pe": ctx["wan_pe_raw"],
                            "wan_cpe": ctx["wan_cpe_raw"],
                            "lan_ip": ctx["lan_raw"]
                        }
                        push_to_online_sheet(payload)

                with st.expander("📄 Preview Generated Configuration", expanded=True):
                    st.code(cfg_out, language="cisco")

            except Exception as exc:
                st.error(f"IP Subnet Calculation Error: {exc}. Please verify format (e.g. 172.17.3.248/29).")


