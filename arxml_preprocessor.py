import xml.etree.ElementTree as ET
import re
import os
import json
from collections import defaultdict
import pandas as pd
from difflib import get_close_matches

NS = {'autosar': 'http://autosar.org/schema/r4.0'}

SERVICE_FILE = "Service_Instance_A14_Ver_3.2 1.arxml"
RBS_FILE = "RBS_A14_Ver_3.2 3.arxml"
OUTPUT_JSON = "pdu_signal_metadata.json"
DEBUG_LOG = "debug_log.txt"

def log_debug(msg):
    with open(DEBUG_LOG, 'a') as f:
        f.write(msg + "\n")

def normalize_name(name):
    return name.replace("SomeIp", "").replace("_SI", "").replace("_", "").lower()

def parse_service_interfaces(service_path):
    service_map = {}
    tree = ET.parse(service_path)
    root = tree.getroot()
    for si in root.findall('.//autosar:SOMEIP-SERVICE-INTERFACE-DEPLOYMENT', NS):
        si_name = si.find('autosar:SHORT-NAME', NS).text
        sid = si.find('.//autosar:SERVICE-INTERFACE-ID', NS)

       
        event_deployments = si.findall('.//autosar:EVENT-DEPLOYMENTS/autosar:SOMEIP-EVENT-DEPLOYMENT', NS)
        event_ids = []
        for ev in event_deployments:
            eid = ev.find('autosar:EVENT-ID', NS)
            if eid is not None:
                event_ids.append(eid.text)

        key = normalize_name(si_name)
        service_map[key] = {
            'service_interface': si_name,
            'service_id': sid.text if sid is not None else '',
            'event_ids': ','.join(event_ids)
        }
    return service_map

def infer_cycle_time_from_name(pdu_name):
    match = re.search(r'_([0-9]{2,4})$', pdu_name)
    if match:
        return str(float(match.group(1)) / 1000)
    return "0.0"

def parse_rbs_pdus(rbs_path):
    tree = ET.parse(rbs_path)
    root = tree.getroot()
    pdu_map = {}

    # Create a lookup for signal lengths
    signal_length_map = {}
    for signal in root.findall('.//autosar:I-SIGNAL', NS):
        signal_name = signal.find('autosar:SHORT-NAME', NS).text
        length_elem = signal.find('autosar:LENGTH', NS)
        signal_length = length_elem.text if length_elem is not None else '0'
        signal_length_map[signal_name] = signal_length

    for pdu in root.findall('.//autosar:I-SIGNAL-I-PDU', NS):
        pdu_name_elem = pdu.find('autosar:SHORT-NAME', NS)
        pdu_name = pdu_name_elem.text if pdu_name_elem is not None else 'Unnamed_PDU'

        length_elem = pdu.find('autosar:LENGTH', NS)
        length = length_elem.text if length_elem is not None else '0'

        timing = pdu.find('.//autosar:CYCLIC-TIMING', NS)
        cycle_time = infer_cycle_time_from_name(pdu_name)
        
        signals = {}
        signal_mappings = pdu.findall('.//autosar:I-SIGNAL-TO-PDU-MAPPINGS/autosar:I-SIGNAL-TO-I-PDU-MAPPING', NS)
        signal_count = 0

        for mapping in signal_mappings:
            sig_ref = mapping.find('autosar:I-SIGNAL-REF', NS)
            if sig_ref is not None:
                sig_name = sig_ref.text.split('/')[-1]
                start_pos = mapping.find('autosar:START-POSITION', NS)
                byte_order = mapping.find('autosar:PACKING-BYTE-ORDER', NS)
                # Fetch signal length from the signal_length_map
                signal_len = signal_length_map.get(sig_name, '0')
                signals[sig_name] = {
                    f"{sig_name}_value": 0,
                    f"{sig_name}_Byte_order": byte_order.text if byte_order is not None else 'Unknown',
                    f"{sig_name}_start_bit": int(start_pos.text) if start_pos is not None else -1,
                    f"{sig_name}_len": signal_len
                }
                signal_count += 1

        pdu_map[pdu_name] = {
            'length': length,
            'cycle_time': cycle_time,
            'signals': signals,
            'total_signals': signal_count
        }
    return pdu_map

def generate_pdu_metadata(service_data, pdu_data):
    messages = {}
    for pdu_name, pdu_info in pdu_data.items():
        key = normalize_name(pdu_name)
        matched_service = service_data.get(key, {'service_interface': 'N/A', 'service_id': '', 'event_ids': ''})
        messages[pdu_name] = {
            'pdu_name': pdu_name,
            'service_interface': matched_service['service_interface'],
            'service_id': matched_service['service_id'],
            'event_ids': matched_service['event_ids'],
            'length': pdu_info['length'],
            'cycle_time': pdu_info['cycle_time'],
            'total_signals': pdu_info['total_signals'],
            'signals': pdu_info['signals']
        }
    return {"Messages": messages}

def extract_signal_compu_methods(rbs_path):
    tree = ET.parse(rbs_path)
    root = tree.getroot()
    compu_methods = []
    
  
    for compu_method in root.findall('.//autosar:COMPU-METHOD', NS):
        compu_name = compu_method.find('autosar:SHORT-NAME', NS).text
      
        for scale in compu_method.findall('.//autosar:COMPU-INTERNAL-TO-PHYS/autosar:COMPU-SCALES/autosar:COMPU-SCALE', NS):
            lower_limit_elem = scale.find('autosar:LOWER-LIMIT', NS)
            lower_limit = lower_limit_elem.text if lower_limit_elem is not None else '0'
        
            try:
                hex_value = f"0x{int(lower_limit):X}" if lower_limit.isdigit() else '0x0'
            except ValueError:
                hex_value = '0x0'
            vt_elem = scale.find('autosar:COMPU-CONST/autosar:VT', NS)
            vt = vt_elem.text if vt_elem is not None else 'No Description'
            compu_methods.append({
                'signal_name': compu_name,
                'raw_value': lower_limit,
                'hex_value': hex_value,
                'description': vt
            })
    
   
    signal_compu_map = {}
    for signal in root.findall('.//autosar:I-SIGNAL', NS):
        signal_name = signal.find('autosar:SHORT-NAME', NS).text
        compu_method_ref = None
    
        phys_props = signal.find('.//autosar:PHYSICAL-PROPS', NS)
        if phys_props is not None:
            data_type_ref = phys_props.find('autosar:SW-DATA-DEF-PROPS/autosar:DATA-TYPE-REF', NS)
            if data_type_ref is not None:
                #
                data_type_path = data_type_ref.text
                data_type = root.find(f".//autosar:APPLICATION-DATA-TYPE[@DEST='APPLICATION-PRIMITIVE-DATA-TYPE' and .='{data_type_path}']", NS)
                if data_type is not None:
                    compu_method_ref = data_type.find('.//autosar:COMPU-METHOD-REF', NS)
        if compu_method_ref is None:
            
            sw_data_def = signal.find('.//autosar:SW-DATA-DEF-PROPS', NS)
            if sw_data_def is not None:
                compu_method_ref = sw_data_def.find('autosar:COMPU-METHOD-REF', NS)
        
        if compu_method_ref is not None:
            compu_name = compu_method_ref.text.split('/')[-1]
           
            for compu in compu_methods:
                if compu['signal_name'] == compu_name:
                    signal_compu_map[signal_name] = f"{compu['raw_value']}.{compu_name}"
                    break
            else:
                signal_compu_map[signal_name] = "0.NoCompuMethod"
        else:
            signal_compu_map[signal_name] = "0.NoCompuMethod"
    
    return compu_methods, signal_compu_map


def infer_cycle_time_details(pdu_name):
    match = re.search(r'_([0-9]{2,4})$', pdu_name)
    if match:
        extracted_number = match.group(1)
        cycle_time = str(float(extracted_number) / 1000)
    else:
        extracted_number = "None"
        cycle_time = "0.0"
    return extracted_number, cycle_time
