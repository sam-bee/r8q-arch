#!/usr/bin/env python3
"""Pack verified per-phone sec_efs Cirrus calibration files as R8QC firmware."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import struct

names = {'rdc_cal', 'rdc_cal_r', 'temp_cal', 'vsc_cal', 'vsc_cal_r', 'isc_cal', 'isc_cal_r'}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input', type=Path, required=True, help='private directory with seven copied sec_efs/cirrus files')
parser.add_argument('--manifest', type=Path, required=True, help='SHA256 manifest retained at read-only extraction')
parser.add_argument('--output', type=Path, required=True, help='new private output directory; never overwrites')
args = parser.parse_args()
expected = {}
for line in args.manifest.read_text().splitlines():
 if not line.strip():
  continue
 digest, name = line.split('  ', 1)
 if not re.fullmatch(r'[0-9a-f]{64}', digest) or name not in names or name in expected:
  parser.error('manifest must contain each of the seven exact filenames once')
 expected[name] = digest
if set(expected) != names:
 parser.error('incomplete calibration manifest')
values = {}
for name in sorted(names):
 p = args.input/name
 if p.is_symlink() or not p.is_file():
  parser.error('missing regular input: '+name)
 data = p.read_bytes()
 if len(data) != 12 or hashlib.sha256(data).hexdigest() != expected[name]:
  parser.error('input length or hash mismatch: '+name)
 text = data.rstrip(b'\0').strip()
 if not re.fullmatch(rb'[0-9]+', text):
  parser.error('invalid decimal calibration: '+name)
 values[name] = int(text)
outputs = {}
for part, suffix in [('bot', '_r'), ('rcv', '')]:
 r, a, v, i = (values['rdc_cal'+suffix], values['temp_cal'], values['vsc_cal'+suffix], values['isc_cal'+suffix])
 if not (1 <= r <= 0xffffff and 0 <= a <= 200):
  parser.error('RDC or ambient out of range for '+part)
 if not (v <= 0x10624 or 0xfef9dc <= v <= 0xffffff):
  parser.error('VSC out of range for '+part)
 if not (i <= 0x4189 or 0xffbe77 <= i <= 0xffffff):
  parser.error('ISC out of range for '+part)
 outputs['cs35l40-'+part+'-factory.cal'] = struct.pack('<4s5I', b'R8QC', 1, r, a, v, i)
args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
os.chmod(args.output, 0o700)
hashes = {}
for name, data in outputs.items():
 p = args.output/name
 with p.open('xb') as f:
  os.chmod(p, 0o600)
  f.write(data)
  f.flush()
  os.fsync(f.fileno())
 hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
provenance = {'format':'R8QC', 'version':1, 'input_sha256':expected, 'output_sha256':hashes,
              'mapping':{'bot':{'i2c_address':'0x40','suffix':'_r'}, 'rcv':{'i2c_address':'0x41','suffix':''}}}
p = args.output/'provenance.json'
p.write_text(json.dumps(provenance, indent=2)+'\n')
os.chmod(p, 0o600)
p = args.output/'files.sha256'
p.write_text(''.join(digest+'  '+name+'\n' for name,digest in sorted(hashes.items())))
os.chmod(p, 0o600)
print('Created two 24-byte factory calibration records in', args.output)
