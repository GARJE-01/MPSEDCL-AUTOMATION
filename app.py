from datetime import datetime
import ipaddress
import re
import jinja2
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="MPSWAN Config Generator", layout="wide")

# Deployed Google Apps Script Web App URL
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbyQiZryKLGqJMRw0QlRdSwSCmJY82lYXeiblINyG-HA1LQKXBpCvdyTcmmsV_STGvqy8g/exec"


def parse_bandwidth_kbps(bw_val):
  if pd.isna(bw_val):
    return 10000
  match = re.search(r"(\d+)", str(bw_val))
  return int(match.group(1)) * 1000 if match else 10000


def build_config(row, template_text):
  wan_pe_raw = str(row["WAN IP PE end"]).strip()
  wan_cpe_raw = str(row.get("WAN IP CPE\xa0", row.get("WAN IP CPE"))).strip()
  lan_raw = str(row.get("LAN IP\xa0", row.get("LAN IP"))).strip()

  wan_pe_iface = ipaddress.ip_interface(wan_pe_raw)
  wan_cpe_iface = ipaddress.ip_interface(wan_cpe_raw)

  lan_net = ipaddress.ip_network(lan_raw, strict=False)
  hosts = list(lan_net.hosts())

  context = {
      "host_name": str(row["Host Name"]).strip(),
      "site_address": str(row["Site Address"]).strip(),
      "local_contact": str(row.get("Local contact Network eng", "")).strip(),
      "lsi_no": (
          str(row["LSI No"]).strip() if pd.notna(row.get("LSI No")) else ""
      ),
      "ra_no": str(row["RA no"]).strip() if pd.notna(row.get("RA no")) else "",
      "wan_pe_raw": wan_pe_raw,
      "wan_cpe_raw": wan_cpe_raw,
      "wan_pe_ip": str(wan_pe_iface.ip),
      "wan_cpe_ip": str(wan_cpe_iface.ip),
      "wan_mask": str(wan_cpe_iface.netmask),
      "lan_raw": lan_raw,
      "lan_first_ip": str(hosts[0]),
      "lan_last_ip": str(hosts[-1]),
      "lan_broadcast_ip": str(lan_net.broadcast_address),
      "lan_cpe_ip": str(hosts[0]),
      "lan_net_id": str(lan_net.network_address),
      "lan_mask": str(lan_net.netmask),
      "bandwidth_kbps": parse_bandwidth_kbps(row.get("Bandwidth (In Mbps)")),
  }

  template = jinja2.Template(template_text)
  return template.render(context), context


st.title("⚡ MPSWAN Site Automation & Online Sync")

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
      "Please ensure 'MPSWAN MPLS Link TN 654-2.xlsx' is uploaded or present in"
      " the repo."
  )
  st.stop()

search_term = st.text_input(
    "🔍 Enter Site Address or Hostname:", placeholder="e.g. BUXWAHA, MAJHAULI"
)

if search_term:
  matches = df[
      df["Site Address"].astype(str).str.contains(search_term, case=False, na=False)
      | df["Host Name"].astype(str).str.contains(search_term, case=False, na=False)
  ]

  if matches.empty:
    st.error("No matching site found.")
  else:
    selected_idx = st.selectbox(
        "Select Site:",
        matches.index,
        format_func=lambda i: (
            f"{matches.loc[i, 'Site Address']}  -->  {matches.loc[i, 'Host"
            " Name']}"
        ),
    )
    row = matches.loc[selected_idx]

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

    config_output, ctx = build_config(row, tpl_jinja)

    col1, col2 = st.columns(2)
    with col1:
      st.download_button(
          label="📥 Download Config (.txt)",
          data=config_output,
          file_name=f"mpsedcl_{row['Host Name']}.txt",
          mime="text/plain",
          type="primary",
      )

    with col2:
      if st.button("🚀 Push / Update to Online Sheet"):
        payload = {
            "host_name": ctx["host_name"],
            "dist": str(row.get("Dist", "")),
            "tehsil": str(row.get("Tehsil/Block", "")),
            "wan_pe": ctx["wan_pe_raw"],
            "wan_cpe": ctx["wan_cpe_raw"],
            "lan_ip": ctx["lan_raw"],
        }
        with st.spinner("Connecting to Google Sheet..."):
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

    with st.expander("📄 Preview Generated Configuration"):
      st.code(config_output, language="cisco")
