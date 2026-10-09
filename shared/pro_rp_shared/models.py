from datetime import date
from typing import Literal
from pydantic import BaseModel, Field

Klauzula = Literal["jawne", "zastrzezone", "poufne", "tajne", "scisle_tajne"]


class Osoba(BaseModel):
    id_osoby: str
    imie: str
    nazwisko: str
    id_jednostki: str
    stanowisko: str = ""
    klauzula_tajnosci: Klauzula = "jawne"
    aktywna: bool = True


class Zadania(BaseModel):
    id_planu: str
    id_zadania: str
    id_jednostek: list[str] = Field(default_factory=list)
    nazwa_zadania: str
    data_utworzenia: date
    data_aktualizacji: date
    status: bool = False
    typ_zadania: Literal["PRZ", "REAL"] = "REAL"
    poziom_realizacji: float = Field(default=0.0, ge=0.0, le=1.0)
    koszt: int = Field(default=0, ge=0)
    zasoby: dict = Field(default_factory=dict)
    klauzula_tajnosci: Klauzula = "scisle_tajne"


class Jednostki(BaseModel):
    id: str
    nazwa: str
    id_planow: list[str] = Field(default_factory=list)
    budzet: int = Field(default=0, ge=0)
    zasoby: dict = Field(default_factory=dict)
    id_regionu: str | None = None
    id_jednostki_nadrzednej: str | None = None
    typ: str | None = None
    pracownicy: list[Osoba] = Field(default_factory=list)


class Plan(BaseModel):
    id_planu: str
    id_planu_nadrzednego: str | None = None
    nazwa_dokumentu: str
    sporzadzil: str
    uzgadnial: list[str] = Field(default_factory=list)
    zatwierdzajacy: str | None = None
    komentarz: str = ""
    data_utworzenia: date
    data_zatwierdzeina: date | None = None
    status_planu: Literal["draft", "in_review", "approved", "rejected"] = "draft"
    status_operacyjny: Literal["prepared", "active"] = "prepared"
    data_aktywacji: str | None = None
    aktywowany_przez: str | None = None
    klauzula_tajnosci: Klauzula = "scisle_tajne"


class Task(BaseModel):
    id: str
    name: str
    region_id: str = "UNKNOWN"
    completion: float = Field(ge=0, le=1)
    status: Literal["planned", "in_progress", "completed", "blocked"]


class Resource(BaseModel):
    id: str
    type: str
    region_id: str = "UNKNOWN"
    quantity: float = Field(ge=0)


class Infrastructure(BaseModel):
    id: str
    name: str
    type: str
    region_id: str = "UNKNOWN"
    operational: bool = True


class OperationalState(BaseModel):
    version: str
    tasks: list[Task] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    infrastructure: list[Infrastructure] = Field(default_factory=list)


class Scenario(BaseModel):
    id: str
    name: str
    description: str = ""
    disabled_resources: list[str] = Field(default_factory=list)
    failed_infrastructure: list[str] = Field(default_factory=list)


class SimulationRequest(BaseModel):
    scenario: Scenario


class SimulationEvent(BaseModel):
    type: str
    message: str
    severity: Literal["info", "warning", "critical"] = "info"


class SimulationResult(BaseModel):
    simulation_id: str
    scenario_id: str
    initial_state_version: str
    readiness_score: float
    events: list[SimulationEvent] = Field(default_factory=list)
    affected_tasks: list[str] = Field(default_factory=list)
