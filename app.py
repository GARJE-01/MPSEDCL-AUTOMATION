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
  if pd.isna(bw_val) or not str(bw_val).strip():
    return 10000
  match = re.search(r"(\d+)", str(bw_val))
  return int(match.group(1)) * 1000 if match else 10000


def render_mpsedcl_config(data_dict):
  """Calculates IP subnet parameters and renders the MPSEDCL template."""
  wan_pe_raw = str(data_dict["wan_pe"]).strip()
  wan_cpe_raw = str(data_dict["wan_cpe"]).strip()
  lan_raw = str(data_dict["lan_ip"]).strip()

  wan_pe_iface = ipaddress.ip_interface(wan_pe_raw)
  wan_cpe_iface = ipaddress.ip_interface(wan_cpe_raw)

  lan_net = ipaddress.ip_network(lan_raw, strict=False)
  hosts = list(lan_net.hosts())

  context = {
      "host_name": str(data_dict["host_name"]).strip(),
      "site_address": str(
          data_dict.get("site_address", data_dict["host_name"])
      ).strip(),
      "local_contact": str(data_dict.get("local_contact", "")).strip(),
      "lsi_no": str(data_dict.get("lsi_no", "")).strip(),
      "ra_no": str(data_dict.get("ra_no", "")).strip(),
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

# Two Tabs: Auto (from Excel) vs Manual Mode
tab_auto, tab_manual = st.tabs(
    ["🔎 Search from Excel (Auto)", "✍️ Manual Entry Mode (Customer Provided)"]
)

# ----------------- TAB 1: AUTO SEARCH -----------------
with tab_auto:
  search_term = st.text_input(
      "🔍 Search Site Address or Hostname:",
      placeholder="e.g. BUXWAHA, MAJHAULI",
      key="auto_search",
  )

  if search_term:
    matches = df[
        df["Site Address"]
        .astype(str)
        .str.contains(search_term, case=False, na=False)
        | df["Host Name"]
        .astype(str)
        .str.contains(search_term, case=False, na=False)
    ]

    if matches.empty:
      st.error("No matching site found in Excel sheet.")
    else:

      def format_site_label(idx):
        addr = str(matches.loc[idx, "Site Address"]).strip()
        host = (
            str(matches.loc[idx, "Host Name"]).strip()
            if pd.notna(matches.loc[idx, "Host Name"])
            else "NO HOSTNAME"
        )
        return f"{addr}  -->  {host}"

      selected_idx = st.selectbox(
          "Select Site:",
          matches.index,
          format_func=format_site_label,
          key="auto_select",
      )
      row = matches.loc[selected_idx]

      wan_pe_val = str(row.get("WAN IP PE end", "")).strip()
      wan_cpe_val = str(
          row.get("WAN IP CPE\xa0", row.get("WAN IP CPE", ""))
      ).strip()
      lan_val = str(row.get("LAN IP\xa0", row.get("LAN IP", ""))).strip()
      host_val = str(row.get("Host Name", "")).strip()

      if (
          not host_val
          or host_val == "nan"
          or not wan_pe_val
          or wan_pe_val == "nan"
      ):
        st.warning(
            "⚠️ This site is missing IP or Host Name details in Excel! Please"
            " switch to the 'Manual Entry Mode' tab to enter customer-provided"
            " IPs."
        )
      else:
        site_data = {
            "host_name": host_val,
            "site_address": str(row.get("Site Address", "")),
            "local_contact": str(row.get("Local contact Network eng", "")),
            "lsi_no": str(row.get("LSI No", "")),
            "ra_no": str(row.get("RA no", "")),
            "wan_pe": wan_pe_val,
            "wan_cpe": wan_cpe_val,
            "lan_ip": lan_val,
            "bandwidth": row.get("Bandwidth (In Mbps)"),
        }

        try:
          config_output, ctx = render_mpsedcl_config(site_data)

          c1, c2 = st.columns(2)
          with c1:
            st.download_button(
                label="📥 Download Config (.txt)",
                data=config_output,
                file_name=f"mpsedcl_{site_data['host_name']}.txt",
                mime="text/plain",
                type="primary",
                key="dl_auto",
            )
          with c2:
            if st.button("🚀 Push / Update to Online Sheet", key="push_auto"):
              payload = {
                  "host_name": ctx["host_name"],
                  "dist": str(row.get("Dist", "")),
                  "tehsil": str(row.get("Tehsil/Block", "")),
                  "wan_pe": ctx["wan_pe_raw"],
                  "wan_cpe": ctx["wan_cpe_raw"],
                  "lan_ip": ctx["lan_raw"],
              }
              push_to_online_sheet(payload)

          with st.expander("📄 Preview Generated Configuration"):
            st.code(config_output, language="cisco")
        except Exception as err:
          st.error(f"Error generating config: {err}")

# ----------------- TAB 2: MANUAL ENTRY MODE -----------------
with tab_manual:
  st.subheader("Manual Site Details (Customer Provided)")
  st.caption(
      "Use this when the master Excel sheet does not have IPs or Hostname."
  )

  # Optional site linkage to autofill District/Tehsil/BW
  link_site = st.checkbox(
      "Link with an existing site from Excel (Autofills District, Tehsil,"
      " Bandwidth)"
  )
  dist_val = ""
  tehsil_val = ""
  bw_val = "10 MBPS"
  site_addr_val = ""
  lsi_val = ""
  ra_val = ""
  contact_val = ""

  if link_site:
    site_query = st.text_input(
        "Search Site Address to link:",
        placeholder="e.g. MANDI_BURHANPUR",
        key="manual_link_search",
    )
    if site_query:
      m_matches = df[
          df["Site Address"]
          .astype(str)
          .str.contains(site_query, case=False, na=False)
      ]
      if not m_matches.empty:
        sel_link = st.selectbox(
            "Select Site to Autofill:",
            m_matches.index,
            format_func=lambda i: (
                f"{m_matches.loc[i, 'Site Address']} ({m_matches.loc[i, 'Dist']})"
            ),
            key="link_sel",
        )
        l_row = m_matches.loc[sel_link]
        dist_val = str(l_row.get("Dist", "")).replace("nan", "")
        tehsil_val = str(l_row.get("Tehsil/Block", "")).replace("nan", "")
        bw_val = str(l_row.get("Bandwidth (In Mbps)", "10 MBPS")).replace(
            "nan", "10 MBPS"
        )
        site_addr_val = str(l_row.get("Site Address", "")).replace("nan", "")
        lsi_val = str(l_row.get("LSI No", "")).replace("nan", "")
        ra_val = str(l_row.get("RA no", "")).replace("nan", "")
        contact_val = str(
            l_row.get("Local contact Network eng", "")
        ).replace("nan", "")

  col_m1, col_m2 = st.columns(2)
  with col_m1:
    m_hostname = st.text_input(
        "Host Name *", placeholder="e.g. AIR_MANDI_BURHANPUR"
    )
    m_wan_pe = st.text_input(
        "WAN IP PE end (with CIDR) *", placeholder="e.g. 172.50.83.205/30"
    )
    m_wan_cpe = st.text_input(
        "WAN IP CPE (with CIDR) *", placeholder="e.g. 172.50.83.206/30"
    )
    m_lan = st.text_input(
        "LAN IP (with CIDR) *", placeholder="e.g. 172.21.159.0/27"
    )

  with col_m2:
    m_bandwidth = st.text_input(
        "Bandwidth",
        value=bw_val if bw_val else "10 MBPS",
        placeholder="e.g. 10 MBPS, 50 MBPS",
    )
    m_site_addr = st.text_input(
        "Site Address",
        value=site_addr_val,
        placeholder="e.g. MANDI_BURHANPUR",
    )
    m_dist = st.text_input(
        "District", value=dist_val, placeholder="e.g. Burhanpur"
    )
    m_tehsil = st.text_input(
        "Tehsil / Block", value=tehsil_val, placeholder="e.g. Burhanpur"
    )

  with st.expander("Additional Optional Fields (LSI / RA / Local Contact)"):
    m_lsi = st.text_input("LSI No", value=lsi_val)
    m_ra = st.text_input("RA no", value=ra_val)
    m_contact = st.text_input("Local Contact Network Eng", value=contact_val)

  if st.button("⚡ Generate Config from Manual Input", type="primary"):
    if not m_hostname or not m_wan_pe or not m_wan_cpe or not m_lan:
      st.error(
          "Please fill in all mandatory fields: Host Name, WAN IP PE, WAN IP"
          " CPE, and LAN IP."
      )
    else:
      manual_data = {
          "host_name": m_hostname.strip(),
          "site_address": (
              m_site_addr.strip() if m_site_addr.strip() else m_hostname.strip()
          ),
          "local_contact": m_contact.strip(),
          "lsi_no": m_lsi.strip(),
          "ra_no": m_ra.strip(),
          "wan_pe": m_wan_pe.strip(),
          "wan_cpe": m_wan_cpe.strip(),
          "lan_ip": m_lan.strip(),
          "bandwidth": m_bandwidth.strip(),
      }

      try:
        cfg_out, manual_ctx = render_mpsedcl_config(manual_data)
        st.session_state["manual_cfg"] = cfg_out
        st.session_state["manual_ctx"] = manual_ctx
        st.session_state["manual_dist"] = m_dist
        st.session_state["manual_tehsil"] = m_tehsil
        st.success("Config generated successfully!")
      except Exception as exc:
        st.error(f"Calculation Error: {exc}. Verify IP and CIDR formats.")

  if "manual_cfg" in st.session_state:
    st.divider()
    mc1, mc2 = st.columns(2)
    with mc1:
      st.download_button(
          label="📥 Download Prepared Config (.txt)",
          data=st.session_state["manual_cfg"],
          file_name=f"mpsedcl_{st.session_state['manual_ctx']['host_name']}.txt",
          mime="text/plain",
          type="primary",
          key="dl_manual",
      )
    with mc2:
      if st.button("🚀 Push / Update to Online Sheet", key="push_manual"):
        m_payload = {
            "host_name": st.session_state["manual_ctx"]["host_name"],
            "dist": st.session_state.get("manual_dist", ""),
            "tehsil": st.session_state.get("manual_tehsil", ""),
            "wan_pe": st.session_state["manual_ctx"]["wan_pe_raw"],
            "wan_cpe": st.session_state["manual_ctx"]["wan_cpe_raw"],
            "lan_ip": st.session_state["manual_ctx"]["lan_raw"],
        }
        push_to_online_sheet(m_payload)

    with st.expander("📄 Preview Generated Configuration", expanded=True):
      st.code(st.session_state["manual_cfg"], language="cisco")
