import unittest

from llmsensor.state import StateEngine, from_telemetry, receive_message, observe_peer, propose_peer, is_uncertain
from llmsensor.state.model import EntityType, Evidence, Level, State, Status, Basis
from llmsensor.state import peer as peer_mod


def seeded():
    E = StateEngine()
    ent, name = "agent:run1", "health"
    E.current[(ent, name)] = State(ent, name, "ok", Status.INFERRED, Basis.OBSERVED, "r", 1, "c", "", 
                                   (Evidence("run1/model_call/0#x", Level.OBSERVATION, "x"),), 1.0, 1.0, 1.0)
    return E, ent, name


class PeerTest(unittest.TestCase):
    def test_entity_type(self):
        self.assertEqual(EntityType.SESSION.value, "session")

    def test_message_informs(self):
        E, _, _ = seeded()
        self.assertTrue(receive_message(E, "j", "i", "msg-1", 5.0))
        r = E.relationships[("session:j", "informs", "session:i")]
        self.assertEqual(r.evidence, ["msg-1"])
        self.assertFalse(receive_message(E, "j", "i", "msg-1", 6.0))
        self.assertEqual(r.evidence, ["msg-1"])

    def test_opinion_is_proposal_only(self):
        E, ent, name = seeded()
        before = (E.current[(ent, name)].value, E.current[(ent, name)].seq, len(E.transitions), len(E.lifecycle))
        p = propose_peer(E, "j", ent, name, "bad", "looks off")
        self.assertEqual(p.author, "session:j")
        self.assertEqual(E.proposals, [p])
        st = E.current[(ent, name)]
        self.assertEqual((st.value, st.seq, len(E.transitions), len(E.lifecycle)), before)
        self.assertFalse(is_uncertain(E, ent, name))

    def test_conflict_contradicts_and_uncertain(self):
        E, ent, name = seeded()
        self.assertEqual(observe_peer(E, "j", ent, name, "bad", "peer/ev1", 7.0), "contradicts")
        r = E.relationships[("peer/ev1", "contradicts", "run1/model_call/0#x")]
        self.assertEqual(r.evidence, ["peer/ev1"])
        self.assertTrue(is_uncertain(E, ent, name))
        self.assertEqual(E.current[(ent, name)].value, "ok")

    def test_agreeing_or_same_evidence_is_not_contradiction(self):
        E, ent, name = seeded()
        self.assertEqual(observe_peer(E, "j", ent, name, "ok", "peer/ev2"), "consistent")
        self.assertEqual(observe_peer(E, "j", ent, name, "bad", "run1/model_call/0#x"), "consistent")
        self.assertFalse(is_uncertain(E, ent, name))
        self.assertFalse([k for k in E.relationships if k[1] == "contradicts"])

    def test_duplicate_evidence_counted_once(self):
        E, ent, name = seeded()
        self.assertEqual(observe_peer(E, "j", ent, name, "bad", "peer/ev1"), "contradicts")
        self.assertEqual(observe_peer(E, "k", ent, name, "bad", "peer/ev1"), "duplicate")
        self.assertEqual(len([k for k in E.relationships if k[1] == "contradicts"]), 1)
        r = E.relationships[("peer/ev1", "contradicts", "run1/model_call/0#x")]
        self.assertEqual(len(r.evidence), 1)
        self.assertEqual(E.uncertain[(ent, name)], {"peer/ev1"})
        self.assertEqual(E.peer_evidence[(ent, name, "peer/ev1")], {"session:j", "session:k"})

    def test_peer_module_never_writes_state(self):
        import inspect
        src = inspect.getsource(peer_mod)
        self.assertNotIn(".value =", src)
        self.assertNotIn("E.current[", src.replace("E.current.get", ""))


if __name__ == "__main__":
    unittest.main()
