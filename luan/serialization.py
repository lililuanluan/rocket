
import os
import re
from types import NoneType
import pandas as  pd
import sys
import argparse










SFIELDS = {
    0x20: ("sfFlags", 4),
    0x22: ("sfCloseTime", 4),
    0x26: ("sfLedgerSequence", 4),
    0x51: ("sfLedgerHash", 32),
    0x73: ("sfSigningPubKey", None), # 变长
    0x74: ("sfTxnSignature", None),  # 变长
    0x1B: ("sfLedgerSequence", 4),
    0x10: ("sfFlags", 4),
    0x14: ("sfLedgerHash", 32),
    0x30: ("sfSigningPubKey", None),
    0x31: ("sfTxnSignature", None),
    0x3F: ("sfValidationPublicKey", None),
    0x72: ("sfSignature", None),
    0x75: ("sfTxnSignature", None),
    0x77: ("sfValidationPublicKey", None),
    0xF1: ("sfIndex", 32),
    # 其他常见字段可继续补充...
}













def parse_validate(val):
    i = 0
    fields = {}
    while i < len(data):











if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="parse a string")
    parser.add_argument("--validate", type=str, help="validation msg")
    parser.add_argument("--statuschange", type=str, help="status change msg")
    args = parser.parse_args()

    with open(val, 'r') as f:
        valmsg = f.read()
        print(valmsg)
        v_match = re.search(r'validation: "+(.*?)"+;?', str(valmsg), re.DOTALL)
        v_str = v_match.group(1) if v_match else None

        if v_str:
            print(v_str)
            v_bytes = codecs.decode(v_str, 'unicode_escape').encode('latin1')
            parse_validate((v_bytes))
