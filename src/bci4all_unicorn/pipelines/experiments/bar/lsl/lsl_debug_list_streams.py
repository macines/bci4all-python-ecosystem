# lsl_debug_list_streams.py
from pylsl import resolve_streams

print("À procura de streams LSL...")
streams = resolve_streams(wait_time=3.0)

if not streams:
    print("Nenhum stream encontrado.")
else:
    print(f"Foram encontrados {len(streams)} stream(s):\n")
    for i, s in enumerate(streams, 1):
        print(f"[{i}]")
        print("  Name:", s.name())
        print("  Type:", s.type())
        print("  Channel count:", s.channel_count())
        print("  Nominal srate:", s.nominal_srate())
        print("  Source ID:", s.source_id())
        print()