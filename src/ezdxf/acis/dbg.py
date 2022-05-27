#  Copyright (c) 2022, Manfred Moitzi
#  License: MIT License
from typing import Iterator, Set, Callable, Dict, Any, List
from .entities import AcisEntity, NONE_REF, Face, Coedge


class AcisDebugger:
    def __init__(self, root: AcisEntity = NONE_REF, start_id: int = 1):
        self._next_id = start_id - 1
        self._root: AcisEntity = root
        self.entities: Dict[int, AcisEntity] = dict()
        if not root.is_none:
            self._store_entities(root)

    @property
    def root(self) -> AcisEntity:
        return self._root

    def _get_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _store_entities(self, entity: AcisEntity) -> None:
        if not entity.is_none and entity.id == -1:
            entity.id = self._get_id()
        self.entities[entity.id] = entity
        for e in vars(entity).values():
            if isinstance(e, AcisEntity) and e.id == -1:
                self._store_entities(e)

    def set_entities(self, entity: AcisEntity) -> None:
        self.entities.clear()
        self._root = entity
        self._store_entities(entity)

    def walk(self, root: AcisEntity = NONE_REF) -> Iterator[AcisEntity]:
        def _walk(entity: AcisEntity):
            if entity.is_none:
                return
            yield entity
            done.add(entity.id)
            for e in vars(entity).values():
                if isinstance(e, AcisEntity) and e.id not in done:
                    yield from _walk(e)

        if root.is_none:
            root = self._root
        done: Set[int] = set()
        yield from _walk(root)

    def filter(
        self, func: Callable[[AcisEntity], bool], entity: AcisEntity = NONE_REF
    ) -> Iterator[Any]:
        if entity.is_none:
            entity = self._root
        yield from filter(func, self.walk(entity))

    def filter_type(
        self, name: str, entity: AcisEntity = NONE_REF
    ) -> Iterator[Any]:
        if entity.is_none:
            entity = self._root
        yield from filter(lambda x: x.type == name, self.walk(entity))

    @staticmethod
    def entity_attributes(entity: AcisEntity, indent: int = 0) -> Iterator[str]:
        indent_str = " " * indent
        for name, data in vars(entity).items():
            if name == "id":
                continue
            yield f"{indent_str}{name}: {data}"

    @staticmethod
    def face_link_structure(face: Face, indent: int = 0) -> Iterator[str]:
        indent_str = " " * indent
        while not face.is_none:
            partner_faces = list(AcisDebugger.partner_faces(face))
            yield f"{indent_str}{str(face)} >> {partner_faces}"
            face = face.next_face

    @staticmethod
    def partner_faces(face: Face) -> Iterator[int]:
        coedges: List[Coedge] = []
        loop = face.loop
        while not loop.is_none:
            coedges.extend(co for co in loop.coedges())
            loop = loop.next_loop
        for coedge in coedges:
            partner_coedge = coedge.partner_coedge
            if not partner_coedge.is_none:
                yield partner_coedge.loop.face.id

