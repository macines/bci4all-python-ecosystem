import random


def gera_seq_aleatoria(num_events: int, num_rounds: int, rng=None):
    """
    Gera a sequência completa de um trial.

    Regras:
    - cada round contém todos os eventos exatamente uma vez
    - a ordem dentro de cada round é aleatória
    - no fim, os rounds são concatenados

    Exemplo:
        num_events = 4
        num_rounds = 3

        possível saída:
        [2, 0, 3, 1,  1, 3, 0, 2,  0, 2, 1, 3]

    Retorna:
        lista de índices em 0..num_events-1
    """
    if num_events < 1:
        raise ValueError("num_events deve ser >= 1")

    if num_rounds < 1:
        raise ValueError("num_rounds deve ser >= 1")

    rng = rng or random.Random()
    seq_total = []

    for _ in range(num_rounds):
        round_seq = list(range(num_events))
        rng.shuffle(round_seq)
        seq_total.extend(round_seq)

    return seq_total