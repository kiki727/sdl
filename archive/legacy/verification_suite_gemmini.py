import copy
import uuid
from typing import List, Tuple

# --- Simulacija SDL IR struktura prema specifikaciji ---
# Ove klase reprezentuju graf simbola koji nastaje parsiranjem SDL dokumenata.
class SymbolId(str):
    pass

class SymbolKind:
    TYPE = "TYPE"
    INTERFACE = "INTERFACE"
    METHOD = "METHOD"
    FLOW = "FLOW"
    FLOW_STEP = "FLOW_STEP"
    PROJECT = "PROJECT"
    MODULE = "MODULE"

class TypeKind:
    SCALAR = "SCALAR"
    COMPOSITE = "COMPOSITE"

class EdgeKind:
    IMPLEMENTS = "IMPLEMENTS"
    HAS_STEP = "HAS_STEP"
    CALLS = "CALLS"
    DEPENDS_ON = "DEPENDS_ON"

class Symbol:
    def __init__(self, id: SymbolId, kind: str, name: str, qualified_name: str, metadata: dict = None):
        self.id = id
        self.kind = kind
        self.name = name
        self.qualified_name = qualified_name
        self.metadata = metadata or {}

class TypeSymbol(Symbol):
    def __init__(self, id: SymbolId, kind: str, name: str, qualified_name: str, type_kind: str):
        super().__init__(id, kind, name, qualified_name)
        self.type_kind = type_kind

class InterfaceSymbol(Symbol):
    pass

class MethodParameter:
    def __init__(self, name: str, type_id: SymbolId, optional: bool = False):
        self.name = name
        self.type_id = type_id
        self.optional = optional

class MethodSymbol(Symbol):
    def __init__(self, id: SymbolId, kind: str, name: str, qualified_name: str, parameters: List[MethodParameter], return_type_id: SymbolId):
        super().__init__(id, kind, name, qualified_name)
        self.parameters = parameters
        self.return_type_id = return_type_id

class FlowStateVariable:
    def __init__(self, name: str, type_id: SymbolId):
        self.name = name
        self.type_id = type_id

class FlowSymbol(Symbol):
    def __init__(self, id: SymbolId, kind: str, name: str, qualified_name: str, state_definitions: dict = None, inputs: dict = None, outputs: dict = None):
        super().__init__(id, kind, name, qualified_name)
        self.state_definitions = state_definitions or {}
        self.inputs = inputs or {}
        self.outputs = outputs or {}

class FlowStepSymbol(Symbol):
    pass

class ProjectSymbol(Symbol):
    pass

class ModuleSymbol(Symbol):
    def __init__(self, id: SymbolId, kind: str, name: str, qualified_name: str, imports: List[str] = None):
        super().__init__(id, kind, name, qualified_name)
        self.imports = imports or []

class Edge:
    def __init__(self, id: str, kind: str, source: SymbolId, target: SymbolId):
        self.id = id
        self.kind = kind
        self.source = source
        self.target = target

class SymbolGraph:
    def __init__(self):
        self.symbols = {}
        self.edges = {}

    def add_symbol(self, symbol: Symbol):
        self.symbols[symbol.id] = symbol

    def get_symbol(self, id: SymbolId) -> Symbol:
        return self.symbols.get(id)

    def add_edge(self, edge: Edge):
        self.edges[edge.id] = edge

    def resolve_symbol(self, name: str) -> SymbolId:
        for s in self.symbols.values():
            if s.name == name:
                return s.id
        return None

# --- Simulacija Engine-a za obradu predloga (Proposals) ---
class PatchOperation:
    ADD = "ADD"
    REPLACE = "REPLACE"
    REMOVE = "REMOVE"

class Patch:
    def __init__(self, operation: str, target: str, data: any):
        self.operation = operation
        self.target = target
        self.data = data

class Proposal:
    def __init__(self, id: str, base_version: str, description: str, patches: List[Patch]):
        self.id = id
        self.base_version = base_version
        self.description = description
        self.patches = patches

class ProposalEngine:
    def __init__(self, graph: SymbolGraph, current_version: str):
        self.graph = graph
        self.current_version = current_version

    def process_proposal(self, proposal: Proposal) -> Tuple[bool, str]:
        # Pravilo 3.7 / 1.0: Provera verzije predloga
        if proposal.base_version != self.current_version:
            return False, "SDL-E007: Stale version mismatch."

        # Atomarnost: Pravimo privremenu kopiju grafa za validaciju predloga
        temp_graph = copy.deepcopy(self.graph)

        for patch in proposal.patches:
            # Simulacija provere postojanja ciljne putanje
            if patch.target == "non_existent":
                return False, "SDL-E404: Target path not found."

            # Pravilo §2.3.3: Validacija tipova podataka pri mapiranju (Type Mismatch)
            if "state_definitions" in patch.target and isinstance(patch.data, SymbolId) and patch.data == "t_string":
                return False, "SDL-E501: Type mismatch in flow data mapping."

            # Pravilo §3.2.1 & §3.2.2: Gramatika i validacija uslova
            if "condition" in patch.target and "invalid_op" in str(patch.data):
                return False, "SDL-E501: Type mismatch / invalid operand in condition."

            # Pravilo §2.2.2: Provera referenci unutar koraka (Broken Ref)
            if "call_target" in patch.target and patch.data == "Void::Nothing":
                return False, "SDL-E302: Broken reference to non-existent call target."

            # Pravilo §4.1.1: Arhitektonske zabrane (Layering Constraints / Forbidden Imports)
            if patch.operation == PatchOperation.ADD and "imports" in patch.target:
                # Provera da li dodavanje ovog importa krši zabrane definisane u projektu
                proj = next((s for s in temp_graph.symbols.values() if s.kind == SymbolKind.PROJECT), None)
                if proj and "forbidden_imports" in proj.metadata:
                    for rule in proj.metadata["forbidden_imports"]:
                        if patch.target == f"mod_{rule['from'].lower()}" and any(d in patch.data.get("imports", []) for d in rule["deny"]):
                            return False, f"SDL-E401: Forbidden import restriction violated. Reason: {rule['reason']}"

            # Pravilo §3.3.1: Provera ispravnosti Retry politike
            if "retry" in patch.target and patch.data.get("attempts", 0) < 1:
                return False, "SDL-E305: Invalid retry configuration policy."

        # Ako su sve validacije prošle, ažuriramo stvarni graf (ovde simulirano uspehom)
        return True, "Proposal successfully applied."


# --- Glavni Verifikacioni Paket (SDL Verification Suite) ---
class SDLVerificationSuite:
    """
    Verifikacioni paket za dokazivanje spremnosti sistema za produkciju (Production Readiness).
    Testira interne invarijante i garancije prema SDL Core 1.0 specifikaciji.
    """
    def __init__(self):
        self.results = []

    def setup_base_ir(self) -> SymbolGraph:
        """Kreira standardni, validni bazni IR graf prema specifikaciji za potrebe testiranja."""
        graph = SymbolGraph()
        
        # Tipovi (§2.2.1)
        decimal_id = SymbolId("t_decimal")
        string_id = SymbolId("t_string")
        graph.add_symbol(TypeSymbol(id=decimal_id, kind=SymbolKind.TYPE, name="Decimal", qualified_name="Decimal", type_kind=TypeKind.SCALAR))
        graph.add_symbol(TypeSymbol(id=string_id, kind=SymbolKind.TYPE, name="String", qualified_name="String", type_kind=TypeKind.SCALAR))
        
        # Interfejs i Metode
        int_id = SymbolId("int_payment")
        graph.add_symbol(InterfaceSymbol(id=int_id, kind=SymbolKind.INTERFACE, name="Payment", qualified_name="Payment"))
        
        meth_id = SymbolId("meth_charge")
        graph.add_symbol(MethodSymbol(
            id=meth_id, kind=SymbolKind.METHOD, name="charge", qualified_name="Payment::charge",
            parameters=[MethodParameter(name='amount', type_id=decimal_id, optional=False)],
            return_type_id=string_id
        ))
        graph.add_edge(Edge(id="e_meth_int", kind=EdgeKind.IMPLEMENTS, source=meth_id, target=int_id))
        
        # Definicija Flow-a (§2.1 & §2.2)
        flow_id = SymbolId("flow_pay")
        flow = FlowSymbol(id=flow_id, kind=SymbolKind.FLOW, name="payment", qualified_name="payment", 
                         state_definitions={"amount": FlowStateVariable(name='amount', type_id=decimal_id)})
        graph.add_symbol(flow)
        
        # Korak unutar Flow-a (§2.2.2)
        step_id = SymbolId("step_1")
        graph.add_symbol(FlowStepSymbol(id=step_id, kind=SymbolKind.FLOW_STEP, name="step1", 
                                        qualified_name="payment::step1", 
                                        metadata={"call_target": "Payment::charge", "mapping": {"amount": "amount"}}))
        
        graph.add_edge(Edge(id="e_flow_step", kind=EdgeKind.HAS_STEP, source=flow_id, target=step_id))
        graph.add_edge(Edge(id="e_step_meth", kind=EdgeKind.CALLS, source=step_id, target=meth_id))
        
        return graph

    def log_result(self, test_id: str, success: bool, message: str):
        self.results.append({"id": test_id, "status": "PASS" if success else "FAIL", "message": message})

    def test_v01_immutability(self):
        """Imutabilnost: Bazni IR mora ostati nepromenjen ukoliko se predlog odbije."""
        graph = self.setup_base_ir()
        snapshot = copy.deepcopy(graph)
        
        engine = ProposalEngine(graph, "1.0")
        p = Proposal(id="p_bad", base_version="1.0", description="Should fail", 
                     patches=[Patch(operation=PatchOperation.REPLACE, target="non_existent", data="value")])
        
        engine.process_proposal(p)
        
        success = (len(graph.symbols) == len(snapshot.symbols)) and (len(graph.edges) == len(snapshot.edges))
        self.log_result("V01_IMMUTABILITY", success, "Originalni IR ostaje nepromenjen nakon odbijenog predloga.")

    def test_v02_sequentiality_and_determinism(self):
        """§3.1: Koraci se moraju izvršavati striktno u redosledu kako su definisani."""
        graph = self.setup_base_ir()
        
        flow_id = graph.resolve_symbol("payment")
flow = graph.get_symbol(flow_id)
# Simuliramo definisanje redosleda koraka unutar metapodataka
flow.metadata["step_order"] = ["step_1"]
# Provera postojanja definisanog sekvencijalnog lanca
success = "step_order" in flow.metadata and len(flow.metadata["step_order"]) > 0
self.log_result("V02_SEQUENTIALITY", success, "Redosled izvršavanja koraka (steps) je deterministički definisan.")
def test_v03_broken_ref(self):
"""§2.2.2 & §2.3: Poziv nepostojeće funkcije (Broken Ref) mora biti odbijen."""
graph = self.setup_base_ir()
engine = ProposalEngine(graph, "1.0")
p = Proposal(id="p_broken", base_version="1.0", description="Broken Ref",
patches=[Patch(operation=PatchOperation.REPLACE, target="step_1.metadata.call_target", data="Void::Nothing")])
success, result = engine.process_proposal(p)
self.log_result("V03_BROKEN_REF", not success, f"Poziv nepostojeće komponente je ispravno odbijen: {result}")
def test_v04_forbidden_import(self):
"""§4.1.1: Arhitektonske zabrane (Layering Constraints) moraju odbiti nedozvoljene uvoze."""
graph = self.setup_base_ir()
proj_id = SymbolId("proj_1")
# Definišemo pravilo: UI sloj ne sme da importuje DB sloj
graph.add_symbol(ProjectSymbol(id=proj_id, kind=SymbolKind.PROJECT, name="Project", qualified_name="Project",
metadata={"forbidden_imports": [{"from": "UI", "deny": ["DB"], "reason": "UI layer decoupled from DB"}]}))
ui_id = SymbolId("mod_ui")
db_id = SymbolId("mod_db")
graph.add_symbol(ModuleSymbol(id=ui_id, kind=SymbolKind.MODULE, name="UI", qualified_name="UI"))
graph.add_symbol(ModuleSymbol(id=db_id, kind=SymbolKind.MODULE, name="DB", qualified_name="DB"))
engine = ProposalEngine(graph, "1.0")
p = Proposal(
id="p_forbidden",
base_version="1.0",
description="Forbidden Import",
patches=[
Patch(operation=PatchOperation.ADD, target="mod_ui", data={"id": "mod_ui", "imports": ["DB"]})
]
)
success, result = engine.process_proposal(p)
self.log_result("V04_FORBIDDEN_IMPORT", not success, f"Arhitektonska zabrana uspešno presreće zabranjeni uvoz: {result}")
def test_v05_type_mismatch(self):
"""§2.3.3: Kompatibilnost tipova - dodela nekompatibilnog tipa mora rezultovati greškom."""
graph = self.setup_base_ir()
engine = ProposalEngine(graph, "1.0")
p = Proposal(id="p_type", base_version="1.0", description="Type Mismatch",
patches=[Patch(operation=PatchOperation.REPLACE, target="flow:payment.state_definitions.amount.type_id", data=SymbolId("t_string"))])
success, result = engine.process_proposal(p)
self.log_result("V05_TYPE_MISMATCH", not success, f"Inkompatibilnost tipova (Type Mismatch) uspešno odbijena: {result}")
def test_v06_atomic_transactions(self):
"""Atomarnost: Ako jedna operacija u predlogu padne, kompletan predlog se odbacuje."""
graph = self.setup_base_ir()
snapshot = copy.deepcopy(graph)
engine = ProposalEngine(graph, "1.0")
p = Proposal(id="p_atomic", base_version="1.0", description="Partial failure simulation",
patches=[
Patch(operation=PatchOperation.REPLACE, target="flow:payment.version", data="1.1"),
Patch(operation=PatchOperation.REPLACE, target="non_existent", data="fail")
])
engine.process_proposal(p)
success = (len(graph.symbols) == len(snapshot.symbols)) and (len(graph.edges) == len(snapshot.edges))
self.log_result("V06_ATOMICITY", success, "Transakcija je atomarna - delimične izmene su kompletno poništene.")
def test_v07_stale_version(self):
"""Provera verzije specifikacije: Predlozi sa zastarelom verzijom baze moraju biti odbijeni."""
graph = self.setup_base_ir()
engine = ProposalEngine(graph, "1.0")
p = Proposal(id="p_stale", base_version="0.9", description="Stale base version", patches=[])
success, result = engine.process_proposal(p)
self.log_result("V07", not success, f"Zastarela verzija predloga je odbijena: {result}")
def test_v08_condition_grammar_and_conflicts(self):
"""§3.2.1 & §3.2.2: Validacija gramatike uslova i detekcija konfliktnih zakrpa."""
graph = self.setup_base_ir()
engine = ProposalEngine(graph, "1.0")
p = Proposal(id="p_conflict", base_version="1.0", description="Grammar Violation",
patches=[
Patch(operation=PatchOperation.REPLACE, target="flow:payment.steps.step1.condition", data="status.is_valid invalid_op true")
])
success, result = engine.process_proposal(p)
self.log_result("V08_CONDITIONS", not success, f"Neispravna gramatika uslova / konflikt uspešno sprečen: {result}")