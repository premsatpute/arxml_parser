import streamlit as st
import pandas as pd
import json
import os
import tempfile
from arxml_preprocessor import (
    parse_service_interfaces,
    parse_rbs_pdus,
    generate_pdu_metadata,
    log_debug,infer_cycle_time_details,
    NS,
    OUTPUT_JSON,
    DEBUG_LOG
)

# Streamlit UI Configuration
st.set_page_config(page_title="PDU Metadata Extractor", layout="wide")

# Title and Introduction
st.title("🚗 PDU Metadata Extractor")
st.markdown("""
Welcome to the PDU Metadata Extractor! This tool parses AUTOSAR ARXML files to extract Service Interface and PDU metadata, 
combining them into a comprehensive JSON output. Upload your Service and RBS ARXML files below to get started.
""")

# File Upload Section
st.header("📤 Upload ARXML Files")
col1, col2 = st.columns(2)

with col1:
    service_file = st.file_uploader("Upload Service ARXML File", type=["arxml"], key="service")
    if service_file:
        st.success(f"Service file uploaded: {service_file.name}")

with col2:
    rbs_file = st.file_uploader("Upload RBS ARXML File", type=["arxml"], key="rbs")
    if rbs_file:
        st.success(f"RBS file uploaded: {rbs_file.name}")

# Tabs for Viewing Data
if service_file or rbs_file:
    tabs = st.tabs(["Generate metadata JSON","Service Interfaces", "PDU Data",  "Debug Log"])

    # Save uploaded files to temporary paths
    with tempfile.NamedTemporaryFile(delete=False, suffix=".arxml") as tmp_service:
        service_path = tmp_service.name
        if service_file:
            tmp_service.write(service_file.getvalue())

    with tempfile.NamedTemporaryFile(delete=False, suffix=".arxml") as tmp_rbs:
        rbs_path = tmp_rbs.name
        if rbs_file:
            tmp_rbs.write(rbs_file.getvalue())

    # Service Interfaces Tab
    with tabs[2]:
        if service_file:
            st.subheader("Parsed Service Interfaces")
            with st.spinner("Parsing service interfaces..."):
                try:
                    service_data = parse_service_interfaces(service_path)
                    df = pd.DataFrame.from_dict(service_data, orient='index').reset_index()
                    df.columns = ['Normalized Key', 'Service Interface', 'Service ID', 'Event IDs']
                    st.dataframe(df, use_container_width=True)
                    st.info(f"Found {len(service_data)} service interfaces.")
                except Exception as e:
                    st.error(f"Error parsing service interfaces: {str(e)}")
                    log_debug(f"UI Error: Parsing service interfaces failed - {str(e)}")

    
    with tabs[1]:
        with tabs[1]:
         if rbs_file:
            st.subheader("Parsed PDU Data")
            with st.spinner("Parsing PDU data..."):
                try:
                    pdu_data = parse_rbs_pdus(rbs_path)
                    for pdu_name, pdu_info in pdu_data.items():
                        with st.expander(f"PDU: {pdu_name}"):
                            st.write(f"**Length:** {pdu_info['length']} bits")
                            st.write(f"**Cycle Time:** {pdu_info['cycle_time']} seconds")
                            st.write(f"**Total Signals:** {pdu_info['total_signals']}")
                            # Process signals to show computation method
                            signal_data = []
                            for sig_name, sig_info in pdu_info['signals'].items():
                                signal_data.append({
                                    "Signal Name": sig_name,
                                    "Value": sig_info.get(f"{sig_name}_value", 0),
                                    "Byte Order": sig_info.get(f"{sig_name}_Byte_order", "Unknown"),
                                    "Start Bit": sig_info.get(f"{sig_name}_start_bit", -1),
                                    "Length": sig_info.get(f"{sig_name}_len", "0"),
                                    "Computation Method (LowerLimit.Name)": sig_info.get(f"{sig_name}_compu_method", "0.NoCompuMethod")
                                })
                            signals_df = pd.DataFrame(signal_data)
                            st.dataframe(signals_df, use_container_width=True)
                    st.info(f"Found {len(pdu_data)} PDUs.")

                    # Cycle Time Computation Details
                    st.subheader("Cycle Time Computation Details")
                    st.markdown("""
                    The cycle time for each PDU is computed by extracting a 2-4 digit number from the end of the PDU name 
                    (e.g., '_100' in 'PDU_Name_100') and dividing it by 1000 to convert to seconds. If no number is found, 
                    the cycle time is set to 0.0 seconds.
                    """)
                    cycle_time_data = []
                    for pdu_name in pdu_data.keys():
                        extracted_number, cycle_time = infer_cycle_time_details(pdu_name)
                        cycle_time_data.append({
                            "PDU Name": pdu_name,
                            "Extracted Number": extracted_number,
                            "Computed Cycle Time (s)": cycle_time
                        })
                    cycle_time_df = pd.DataFrame(cycle_time_data)
                    st.dataframe(cycle_time_df, use_container_width=True)
                except Exception as e:
                    st.error(f"Error parsing PDU data: {str(e)}")
                    log_debug(f"UI Error: Parsing PDU data failed - {str(e)}")
    # Generated Metadata Tab
    with tabs[0]:
        st.subheader("Generated PDU Metadata")
        if service_file and rbs_file:
            # Input field for custom JSON filename
            default_filename = OUTPUT_JSON
            json_filename = st.text_input(
                "Output JSON Filename",
                value=default_filename,
                help="Enter the filename for the generated JSON file (e.g., pdu_signal_metadata.json)"
            )
            if not json_filename.endswith(".json"):
                json_filename += ".json"

            if st.button("Generate Metadata JSON", key="generate"):
                with st.spinner("Generating metadata..."):
                    try:
                        service_data = parse_service_interfaces(service_path)
                        pdu_data = parse_rbs_pdus(rbs_path)
                        final_metadata = generate_pdu_metadata(service_data, pdu_data)
                        
                        # Display metadata in expandable JSON viewer
                        with st.expander("View Generated Metadata JSON", expanded=False):
                            st.json(final_metadata)
                        
                        # Save to temporary file in text mode
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode='w') as tmp_json:
                            json.dump(final_metadata, tmp_json, indent=2)
                            tmp_json_path = tmp_json.name
                        
                        # Read file in binary mode for download
                        with open(tmp_json_path, 'rb') as f:
                            st.download_button(
                                label="Download Metadata JSON",
                                data=f,
                                file_name=json_filename,
                                mime="application/json",
                                key="download_json"
                            )
                        
                        # Display JSON content in text area below download button
                        st.markdown("### JSON Content Preview")
                        st.text_area(
                            "Generated JSON Content",
                            value=json.dumps(final_metadata, indent=2),
                            height=300,
                            disabled=True,
                            key="json_preview"
                        )
                        
                        st.success(f"Metadata generated successfully! Downloaded as {json_filename}")
                        log_debug(f"UI: Metadata JSON generated and downloaded as {json_filename}")
                    except Exception as e:
                        st.error(f"Error generating metadata: {str(e)}")
                        log_debug(f"UI Error: Metadata generation failed - {str(e)}")
        else:
            st.warning("Please upload both Service and RBS ARXML files to generate metadata.")

    # Debug Log Tab
    with tabs[3]:
        st.subheader("Debug Log")
        if os.path.exists(DEBUG_LOG):
            with open(DEBUG_LOG, 'r') as f:
                log_content = f.read()
            st.text_area("Debug Log Content", log_content, height=300)
        else:
            st.info("No debug log available yet.")

    # Clean up temporary files
    if os.path.exists(service_path):
        os.unlink(service_path)
    if os.path.exists(rbs_path):
        os.unlink(rbs_path)

else:
    st.info("Upload ARXML files to begin parsing and generating metadata.")

