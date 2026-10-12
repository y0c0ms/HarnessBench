"""Session slots: a run queues behind the sessions in flight and starts as soon as one frees."""
import threading
import time

from agent_bench.runner import acquire_slot


def test_queued_job_starts_only_when_a_slot_frees(tmp_path):
    first = acquire_slot(tmp_path, 1)
    got = []
    waiter = threading.Thread(target=lambda: got.append(acquire_slot(tmp_path, 1, poll_s=0.05)))
    waiter.start()
    time.sleep(0.3)
    assert got == []                       # the only slot is held: the second job is still queued
    first.close()                          # the running job finishes and releases its slot
    waiter.join(timeout=5)
    assert len(got) == 1                   # the queued job took the freed slot
    got[0].close()


def test_slot_count_caps_concurrency_across_handles(tmp_path):
    held = [acquire_slot(tmp_path, 2), acquire_slot(tmp_path, 2)]
    extra = []
    waiter = threading.Thread(target=lambda: extra.append(acquire_slot(tmp_path, 2, poll_s=0.05)))
    waiter.start()
    time.sleep(0.3)
    assert extra == []                     # two slots of two are held: a third session must wait
    held[1].close()
    waiter.join(timeout=5)
    assert len(extra) == 1
    for fh in held[:1] + extra:
        fh.close()
