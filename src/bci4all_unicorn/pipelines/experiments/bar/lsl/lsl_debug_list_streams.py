"""
Nome do ficheiro: lsl_debug_list_streams.py

Descrição:
    Script de diagnóstico para deteção e listagem de streams LSL
    disponíveis no sistema ou na rede local.

Objetivo:
    Verificar se o sender está a publicar corretamente um stream
    LSL e identificar as suas propriedades principais, como nome,
    tipo, número de canais, frequência nominal e source ID.

Funcionalidades:
    - pesquisa de todos os streams LSL disponíveis
    - listagem detalhada dos streams encontrados
    - apresentação de nome, tipo, channel count, nominal srate e source ID
    - apoio ao diagnóstico de problemas de ligação entre sender e receiver

Utilização típica:
    Executar este ficheiro com o sender ativo para confirmar
    se o stream "AlphaRMS" está visível e corretamente publicado.

Fluxo:
    procura de streams LSL -> listagem de propriedades -> validação do sender
"""
# Importa a função resolve_streams da biblioteca pylsl.
# Esta função procura todos os streams LSL disponíveis na rede/localmente.
from pylsl import resolve_streams

# Mostra no terminal uma mensagem para indicar que a pesquisa de streams começou.
print("À procura de streams LSL...")

# Procura streams LSL durante até 3 segundos.
# Se encontrar streams nesse intervalo, devolve uma lista com esses streams.
# Se não encontrar nenhum, devolve uma lista vazia.
streams = resolve_streams(wait_time=3.0)

# Verifica se a lista de streams está vazia.
if not streams:
    # Caso não exista nenhum stream encontrado, mostra esta mensagem.
    print("Nenhum stream encontrado.")
else:
    # Caso existam streams, mostra quantos foram encontrados.
    print(f"Foram encontrados {len(streams)} stream(s):\n")

    # Percorre a lista de streams encontrados.
    # enumerate(..., 1) faz com que a contagem comece em 1 em vez de 0.
    for i, s in enumerate(streams, 1):
        # Mostra o número do stream atual.
        print(f"[{i}]")

        # Mostra o nome do stream.
        # Exemplo: "AlphaRMS"
        print("  Name:", s.name())

        # Mostra o tipo do stream.
        # Exemplo: "METRIC" ou "EEG"
        print("  Type:", s.type())

        # Mostra o número de canais que o stream transmite.
        # Exemplo: 1 para uma métrica única, 8 para EEG multicanal.
        print("  Channel count:", s.channel_count())

        # Mostra a frequência nominal de amostragem do stream.
        # Se for irregular/event-based, pode aparecer 0.0.
        print("  Nominal srate:", s.nominal_srate())

        # Mostra o identificador único da origem do stream.
        # Serve para distinguir streams com o mesmo nome.
        print("  Source ID:", s.source_id())

        # Imprime uma linha em branco para separar visualmente cada stream.
        print()