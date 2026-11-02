from datetime import datetime
import ipaddress
import re
import jinja2
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="MPSWAN Config Automation", layout="wide")

# Deployed Google Apps Script Web App URL
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbwTOMwPX41Dd1_H1vzCRij7iS2CJnKABx8znesk7AaPrE-rQwwFtXq8OLlDQQIM3YQ/exec"


def parse_bandwidth_kbps(bw_val):
  if pd.isna(bw_val) or not str(bw_val).strip():
    return 10000
  match = re.search(r"(\d+)", str(bw_val))
  return int(match.group(1)) * 1000 if match else 10000


def render_mpsedcl_config(data_dict):
  """Calculates IP subnet masks, gateways, broadcast and renders MPSEDCL template."""
  wan_pe_raw = str(data_dict["wan_pe"]).strip()
  wan_cpe_raw = str(data_dict["wan_cpe"]).strip()
  lan_raw = str(data_dict["lan_ip"]).strip()

  # Auto-append /30 if user only typed plain IP without prefix
  if "/" not in wan_pe_raw:
    wan_pe_raw += "/30"
  if "/" not in wan_cpe_raw:
    wan_cpe_raw += "/30"

  wan_pe_iface = ipaddress.ip_interface(wan_pe_raw)
  wan_cpe_iface = ipaddress.ip_interface(wan_cpe_raw)

  lan_net = ipaddress.ip_network(lan_raw, strict=False)
  hosts = list(lan_net.hosts())

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
      "lan_raw": str(lan_net),
      "lan_first_ip": str(hosts[0]),
      "lan_last_ip": str(hosts[-1]),
      "lan_broadcast_ip": str(lan_net.broadcast_address),
      "lan_cpe_ip": str(hosts[0]),
      "lan_net_id": str(lan_net.network_address),
      "lan_mask": str(lan_net.netmask),
      "bandwidth_kbps": parse_bandwidth_kbps(data_dict.get("bandwidth", 10)),
  }

  with open("MPSEDCL_Template.txt", "r") as f:
    raw_tpl = f.read()

  tpl_jinja = (
      raw_tpl.replace("AIR_MARKFED_DAMOH", "{{ host_name }}")
      .replace("MARKFED_DAMOH", "{{ site_address }}")
      .replace("MRS. Varsha 7725856340", "{{ local_contact }}")
      .replace("14723385", "{{ lsi_no }}")
      .replace("3067991", "{{ ra_no }}")
      .replace("172.49.111.13/30", "{{ wan_pe_raw }}")
      .replace("172.49.111.14/30", "{{ wan_cpe_raw }}")
      .replace("172.17.117.128/27", "{{ lan_raw }}")
      .replace(
          "172.17.117.129 - 172.17.117.158",
          "{{ lan_first_ip }} - {{ lan_last_ip }}",
      )
      .replace(
          "172.17.117.159 = broadcast", "{{ lan_broadcast_ip }} = broadcast"
      )
      .replace("hostname <hostname>", "hostname {{ host_name }}")
      .replace(
          "ip add 172.52.134.170 255.255.255.252",
          "ip add {{ wan_cpe_ip }} {{ wan_mask }}",
      )
      .replace("bandwidth 10000", "bandwidth {{ bandwidth_kbps }}")
      .replace("172.52.134.169", "{{ wan_pe_ip }}")
      .replace("172.17.249.65", "{{ lan_cpe_ip }}")
      .replace("172.17.249.64", "{{ lan_net_id }}")
      .replace("255.255.255.240", "{{ lan_mask }}")
      .replace("172.52.134.170", "{{ wan_cpe_ip }}")
  )

  template = jinja2.Template(tpl_jinja)
  return template.render(context), context


def push_to_online_sheet(payload):
  """Sends row details to Google Apps Script Webhook."""
  with st.spinner("Connecting to Online Google Sheet..."):
    try:
      res = requests.post(APPS_SCRIPT_URL, json=payload, timeout=20)
      if res.status_code == 200:
        try:
          res_json = res.json()
          st.success(res_json.get("message", "Success!"))
        except ValueError:
          st.success("Data pushed successfully.")
      else:
        st.error(
            f"Error communicating with Google Sheet ({res.status_code}):"
            f" {res.text}"
        )
    except Exception as err:
      st.error(f"Request failed: {err}")


st.title("⚡ MPSWAN Site Automation & Config Generator")

# Load Excel File
uploaded_file = st.sidebar.file_uploader(
    "Upload Site Master Sheet (.xlsx)", type=["xlsx"]
)
excel_path = (
    uploaded_file if uploaded_file else "MPSWAN MPLS Link TN 654-2.xlsx"
)

try:
  df = pd.read_excel(excel_path, sheet_name="Sheet1")
except Exception as e:
  st.warning(
      "Please ensure 'MPSWAN MPLS Link TN 654-2.xlsx' is present or upload it."
  )
  st.stop()

# 1. Search Site Address to match in Excel sheet
search_query = st.text_input(
    "🔍 Search Site Address in Excel Sheet:",
    placeholder="e.g. MANDI_BURHANPUR, JOBAT, RAJNAGAR",
)

if search_query:
  matches = df[
      df["Site Address"]
      .astype(str)
      .str.contains(search_query, case=False, na=False)
  ]

  if matches.empty:
    st.error("No matching Site Address found in Excel sheet.")
  else:

    def format_option(idx):
      addr = str(matches.loc[idx, "Site Address"]).strip()
      dist = str(matches.loc[idx, "Dist"]).strip()
      tehsil = str(matches.loc[idx, "Tehsil/Block"]).strip()
      return f"{addr}  |  Dist: {dist}  |  Block: {tehsil}"

    selected_idx = st.selectbox(
        "Select Matching Site:", matches.index, format_func=format_option
    )
    row = matches.loc[selected_idx]

    # Pre-extracted details from Excel
    site_address_val = str(row.get("Site Address", "")).replace("nan", "")
    dist_val = str(row.get("Dist", "")).replace("nan", "")
    tehsil_val = str(row.get("Tehsil/Block", "")).replace("nan", "")
    bw_val = str(row.get("Bandwidth (In Mbps)", "10 MBPS")).replace(
        "nan", "10 MBPS"
    )
    lsi_val = str(row.get("LSI No", "")).replace("nan", "")
    ra_val = str(row.get("RA no", "")).replace("nan", "")
    contact_val = str(row.get("Local contact Network eng", "")).replace(
        "nan", ""
    )

    # Pre-fill defaults if present in Excel, otherwise empty for customer input
    excel_host = str(row.get("Host Name", "")).replace("nan", "")
    excel_wan_pe = str(row.get("WAN IP PE end", "")).replace("nan", "")
    excel_wan_cpe = str(
        row.get("WAN IP CPE\xa0", row.get("WAN IP CPE", ""))
    ).replace("nan", "")
    excel_lan = str(row.get("LAN IP\xa0", row.get("LAN IP", ""))).replace(
        "nan", ""
    )

    st.markdown("---")
    st.subheader(f"Site Metadata from Excel: `{site_address_val}`")

    # Display read-only fetched info badges
    m1, m2, m3, m4 = st.columns(4)
    m1.info(f"**District:** {dist_val}")
    m2.info(f"**Tehsil/Block:** {tehsil_val}")
    m3.info(f"**Bandwidth:** {bw_val}")
    m4.info(f"**RA No:** {ra_val if ra_val else 'Pending'}")

    st.markdown("### ✍️ Customer-Provided Parameters")
    st.caption(
        "Enter the values supplied by the customer for this new branch:"
    )

    col1, col2 = st.columns(2)
    with col1:
      in_hostname = st.text_input(
          "Host Name *",
          value=(
              excel_host
              if excel_host
              else f"AIR_{site_address_val}".replace(" ", "_")
          ),
          placeholder="e.g. AIR_MANDI_BURHANPUR",
      )
      in_lan = st.text_input(
          "LAN IP (with prefix/CIDR) *",
          value=excel_lan,
          placeholder="e.g. 172.21.159.0/27 or 172.17.214.80/28",
      )

    with col2:
      in_wan_pe = st.text_input(
          "WAN IP PE end *",
          value=excel_wan_pe,
          placeholder="e.g. 172.50.83.205/30 (or plain IP)",
      )
      in_wan_cpe = st.text_input(
          "WAN IP CPE *",
          value=excel_wan_cpe,
          placeholder="e.g. 172.50.83.206/30 (or plain IP)",
      )

    # Optional local contact override
    with st.expander("Local Contact / LSI Details (from Excel)"):
      in_contact = st.text_input(
          "Local Contact Network Eng", value=contact_val
      )
      in_lsi = st.text_input("LSI No", value=lsi_val)

    if st.button("⚡ Generate Configuration", type="primary"):
      if not in_hostname or not in_wan_pe or not in_wan_cpe or not in_lan:
        st.error(
            "Please fill in all customer-provided fields (Host Name, WAN IP PE,"
            " WAN IP CPE, and LAN IP)."
        )
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
            "bandwidth": bw_val,
        }

        try:
          cfg_out, ctx = render_mpsedcl_config(site_data)
          st.session_state["active_cfg"] = cfg_out
          st.session_state["active_ctx"] = ctx
          st.session_state["active_dist"] = dist_val
          st.session_state["active_tehsil"] = tehsil_val
          st.success("✅ Configuration generated successfully!")
        except Exception as exc:
          st.error(f"IP Calculation Error: {exc}. Please verify subnet format.")

    # Show download & push actions once config is generated
    if "active_cfg" in st.session_state:
      st.markdown("---")
      c_down, c_push = st.columns(2)
      with c_down:
        st.download_button(
            label="📥 Download Config (.txt)",
            data=st.session_state["active_cfg"],
            file_name=f"mpsedcl_{st.session_state['active_ctx']['host_name']}.txt",
            mime="text/plain",
            type="primary",
        )

      with c_push:
        if st.button("🚀 Push / Update to Online Sheet"):
          payload = {
              "host_name": st.session_state["active_ctx"]["host_name"],
              "dist": st.session_state.get("active_dist", ""),
              "tehsil": st.session_state.get("active_tehsil", ""),
              "wan_pe": st.session_state["active_ctx"]["wan_pe_raw"],
              "wan_cpe": st.session_state["active_ctx"]["wan_cpe_raw"],
              "lan_ip": st.session_state["active_ctx"]["lan_raw"],
          }
          push_to_online_sheet(payload)

      with st.expander("📄 Preview Generated Configuration", expanded=True):
        st.code(st.session_state["active_cfg"], language="cisco")
