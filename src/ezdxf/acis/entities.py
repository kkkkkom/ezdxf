#  Copyright (c) 2022, Manfred Moitzi
#  License: MIT License
from __future__ import annotations
from typing import Union, List, Dict, Callable, Type, Any, Sequence
import abc

from . import sab, sat, const, hdr
from .const import Features
from .abstract import DataLoader, AbstractEntity, DataExporter
from ezdxf.math import Matrix44, Vec3, NULLVEC

Factory = Callable[[AbstractEntity], "AcisEntity"]

ENTITY_TYPES: Dict[str, Type[AcisEntity]] = {}
INF = float("inf")


def load(
    data: Union[str, Sequence[str], bytes, bytearray, Sequence[bytes]]
) -> List[Body]:
    """Returns a list of :class:`Body` entities from :term:`SAT` or :term:`SAB`
    data. Accepts :term:`SAT` data as a single string or a sequence of strings
    and :term:`SAB` data as bytes, bytearray or a sequence of bytes.

    Example for loading ACIS data from a DXF entity based on
    :class:`ezdxf.entities.Body`::

        from ezdxf.acis import api as acis
        ...

        for e in msp.query("3DSOLID"):
            bodies = acis.load(e.acis_data)
            ...

    .. warning::

        Only a limited count of :term:`ACIS` entities is supported, all
        unsupported entities are loaded as ``NONE_ENTITY`` and their data is
        lost. Exporting such ``NONE_ENTITIES`` will raise an :class:`ExportError`
        exception.

        To emphasize that again: **It is not possible to load and re-export
        arbitrary ACIS data!**

    """
    if isinstance(data, Sequence):
        if len(data) == 0:
            return []
        if isinstance(data[0], str):
            return SatLoader.load(data)  # type: ignore
        elif isinstance(data[0], (bytes, bytearray)):
            return SabLoader.load(data)  # type: ignore
    if isinstance(data, (bytes, bytearray)):
        return SabLoader.load(data)
    elif isinstance(data, str):
        return SatLoader.load(data)
    raise TypeError(f"invalid type of data: {type(data)}")


def export_sat(bodies: Sequence[Body], version: int = 700) -> List[str]:
    """Export one or more :class:`Body` entities as text based :term:`SAT` data.

    Minimum :term:`ACIS` version is 700.

    Raises:
        ExportError: ACIS structures contain unsupported entities
        InvalidLinkStructure: corrupt link structure

    """
    exporter = sat.SatExporter(_setup_export_header(version))
    for body in bodies:
        exporter.export(body)
    return exporter.dump_sat()


def export_sab(bodies: Sequence[Body], version: int = 700) -> bytes:
    """Export one or more :class:`Body` entities as binary encoded :term:`SAB`
    data.

    Minimum :term:`ACIS` version is 700.

    Raises:
        ExportError: ACIS structures contain unsupported entities
        InvalidLinkStructure: corrupt link structure

    """
    exporter = sab.SabExporter(_setup_export_header(version))
    for body in bodies:
        exporter.export(body)
    return exporter.dump_sab()


def _setup_export_header(version) -> hdr.AcisHeader:
    if not const.is_valid_export_version(version):
        raise const.ExportError(f"invalid export version: {version}")
    header = hdr.AcisHeader()
    header.set_version(version)
    return header


def register(cls: Type[AcisEntity]):
    ENTITY_TYPES[cls.type] = cls
    return cls


class NoneEntity:
    type: str = const.NONE_ENTITY_NAME

    @property
    def is_none(self) -> bool:
        return self.type == const.NONE_ENTITY_NAME


NONE_REF: Any = NoneEntity()


class AcisEntity(NoneEntity):
    """Base ACIS entity which also represents unsupported entities.

    Unsupported entities are entities whose internal structure are not fully
    known or user defined entity types.

    The content of these unsupported entities is not loaded and lost by
    exporting such entities, therefore exporting unsupported entities raises
    an :class:`ExportError` exception.

    """

    type: str = "unsupported-entity"
    id: int
    attributes: AcisEntity = NONE_REF

    def load(self, loader: DataLoader, entity_factory: Factory) -> None:
        """Load the ACIS entity content from `loader`."""
        self.restore_common(loader, entity_factory)
        self.restore_data(loader)

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        """Load the common part of an ACIS entity."""
        pass

    def restore_data(self, loader: DataLoader) -> None:
        """Load the data part of an ACIS entity."""
        pass

    def export(self, exporter: DataExporter) -> None:
        """Write the ACIS entity content to `exporter`."""
        self.write_common(exporter)
        self.write_data(exporter)

    def write_common(self, exporter: DataExporter) -> None:
        """Write the common part of the ACIS entity.

        It is not possible to export :class:`Body` entities including
        unsupported entities, doing so would cause data loss or worse data
        corruption!

        """
        raise const.ExportError(f"unsupported entity type: {self.type}")

    def write_data(self, exporter: DataExporter) -> None:
        """Write the data part of the ACIS entity."""
        pass


def restore_entity(
    expected_type: str, loader: DataLoader, entity_factory: Factory
) -> Any:
    raw_entity = loader.read_ptr()
    if raw_entity.is_null_ptr:
        return NONE_REF
    if raw_entity.name.endswith(expected_type):
        return entity_factory(raw_entity)
    else:
        raise const.ParsingError(
            f"expected entity type '{expected_type}', got '{raw_entity.name}'"
        )


@register
class Transform(AcisEntity):
    type: str = "transform"
    matrix = Matrix44()

    def restore_data(self, loader: DataLoader) -> None:
        # Here comes an ugly hack, but SAT and SAB store the matrix data in
        # quiet different ways:
        if isinstance(loader, sab.SabDataLoader):
            # SAB matrix data is stored as a literal string and looks like a SAT
            # record: "1 0 0 0 1 0 0 0 1 0 0 0 1 no_rotate no_reflect no_shear"
            values = loader.read_str().split(" ")
            # delegate to SAT format:
            loader = sat.SatDataLoader(values, loader.version)
        data = [loader.read_double() for _ in range(12)]
        # insert values of the last matrix column (0, 0, 0, 1)
        data.insert(3, 0.0)
        data.insert(7, 0.0)
        data.insert(11, 0.0)
        data.append(1.0)
        self.matrix = Matrix44(data)

    def write_common(self, exporter: DataExporter) -> None:
        def write_double(value: float):
            data.append(f"{value:g}")

        data: List[str] = []
        for row in self.matrix.rows():
            write_double(row[0])
            write_double(row[1])
            write_double(row[2])
        test_vector = Vec3(1, 0, 0)
        result = self.matrix.transform_direction(test_vector)
        # A uniform scaling in x- y- and z-axis is assumed:
        write_double(round(result.magnitude, 6))  # scale factor
        is_rotated = not result.normalize().isclose(test_vector)
        data.append("rotate" if is_rotated else "no_rotate")
        data.append("no_reflect")
        data.append("no_shear")
        # SAT and SAB store the matrix data in quiet different ways:
        if isinstance(exporter, sat.SatDataExporter):
            exporter.data.extend(data)
        else:  # SAB stores the SAT transformation data as literal string
            exporter.write_literal_str(" ".join(data))


@register
class AsmHeader(AcisEntity):
    type: str = "asmheader"

    def __init__(self, version: str = ""):
        self.version = version

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        self.version = loader.read_str()

    def write_common(self, exporter: DataExporter) -> None:
        exporter.write_str(self.version)


class SupportsPattern(AcisEntity):
    pattern: Pattern = NONE_REF

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        if loader.version >= Features.PATTERN:
            self.pattern = restore_entity("pattern", loader, entity_factory)

    def write_common(self, exporter: DataExporter) -> None:
        exporter.write_ptr(self.pattern)


@register
class Body(SupportsPattern):
    type: str = "body"
    pattern: Pattern = NONE_REF
    lump: Lump = NONE_REF
    wire: Wire = NONE_REF
    transform: "Transform" = NONE_REF

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.lump = restore_entity("lump", loader, entity_factory)
        self.wire = restore_entity("wire", loader, entity_factory)
        self.transform = restore_entity("transform", loader, entity_factory)

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_ptr(self.lump)
        exporter.write_ptr(self.wire)
        exporter.write_ptr(self.transform)


@register
class Wire(SupportsPattern):  # not implemented
    type: str = "wire"


@register
class Pattern(AcisEntity):  # not implemented
    type: str = "pattern"


@register
class Lump(SupportsPattern):
    type: str = "lump"
    next_lump: Lump = NONE_REF
    shell: Shell = NONE_REF
    body: Body = NONE_REF

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.next_lump = restore_entity("lump", loader, entity_factory)
        self.shell = restore_entity("shell", loader, entity_factory)
        self.body = restore_entity("body", loader, entity_factory)

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_ptr(self.next_lump)
        exporter.write_ptr(self.shell)
        exporter.write_ptr(self.body)


@register
class Shell(SupportsPattern):
    type: str = "shell"
    next_shell: Shell = NONE_REF
    subshell: Subshell = NONE_REF
    face: Face = NONE_REF
    wire: Wire = NONE_REF
    lump: Lump = NONE_REF

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.next_shell = restore_entity("next_shell", loader, entity_factory)
        self.subshell = restore_entity("subshell", loader, entity_factory)
        self.face = restore_entity("face", loader, entity_factory)
        self.wire = restore_entity("wire", loader, entity_factory)
        self.lump = restore_entity("lump", loader, entity_factory)

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_ptr(self.next_shell)
        exporter.write_ptr(self.subshell)
        exporter.write_ptr(self.face)
        exporter.write_ptr(self.wire)
        exporter.write_ptr(self.lump)


@register
class Subshell(SupportsPattern):  # not implemented
    type: str = "subshell"


@register
class Face(SupportsPattern):
    type: str = "face"
    next_face: "Face" = NONE_REF
    loop: Loop = NONE_REF
    shell: Shell = NONE_REF
    subshell: Subshell = NONE_REF
    surface: Surface = NONE_REF
    sense = True  # True = reversed; False = forward
    double_sided = False  # True = double; False = single
    containment = False  # if double_sided: True = in, False = out

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.next_face = restore_entity("face", loader, entity_factory)
        self.loop = restore_entity("loop", loader, entity_factory)
        self.shell = restore_entity("shell", loader, entity_factory)
        self.subshell = restore_entity("subshell", loader, entity_factory)
        self.surface = restore_entity("surface", loader, entity_factory)
        self.sense = loader.read_bool("reversed", "forward")
        self.double_sided = loader.read_bool("double", "single")
        if self.double_sided:
            self.containment = loader.read_bool("in", "out")

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_ptr(self.next_face)
        exporter.write_ptr(self.loop)
        exporter.write_ptr(self.shell)
        exporter.write_ptr(self.subshell)
        exporter.write_ptr(self.surface)
        exporter.write_bool(self.sense, "reversed", "forward")
        exporter.write_bool(self.double_sided, "double", "single")
        if self.double_sided:
            exporter.write_bool(self.containment, "in", "out")


@register
class Surface(SupportsPattern):
    type: str = "surface"
    u_bounds = INF, INF
    v_bounds = INF, INF

    def restore_data(self, loader: DataLoader) -> None:
        self.u_bounds = loader.read_interval(), loader.read_interval()
        self.v_bounds = loader.read_interval(), loader.read_interval()

    def write_data(self, exporter: DataExporter):
        exporter.write_interval(self.u_bounds[0])
        exporter.write_interval(self.u_bounds[1])
        exporter.write_interval(self.v_bounds[0])
        exporter.write_interval(self.v_bounds[1])


@register
class Plane(Surface):
    type: str = "plane-surface"
    origin = Vec3(0, 0, 0)
    normal = Vec3(1, 0, 0)  # pointing outside
    u_dir = Vec3(1, 0, 0)  # unit vector!
    reverse_v = True  # True = reverse_v; False = forward_v

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.origin = Vec3(loader.read_vec3())
        self.normal = Vec3(loader.read_vec3())
        self.u_dir = Vec3(loader.read_vec3())
        self.reverse_v = loader.read_bool("reverse_v", "forward_v")

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_loc_vec3(self.origin)
        exporter.write_dir_vec3(self.normal)
        exporter.write_dir_vec3(self.u_dir)
        exporter.write_bool(self.reverse_v, "reverse_v", "forward_v")

    @property
    def v_dir(self):
        v_dir = self.normal.cross(self.u_dir)
        if self.reverse_v:
            return -v_dir
        return v_dir


@register
class Loop(SupportsPattern):
    type: str = "loop"
    next_loop: Loop = NONE_REF
    coedge: Coedge = NONE_REF
    face: Face = NONE_REF  # parent/owner

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.next_loop = restore_entity("loop", loader, entity_factory)
        self.coedge = restore_entity("coedge", loader, entity_factory)
        self.face = restore_entity("face", loader, entity_factory)

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_ptr(self.next_loop)
        exporter.write_ptr(self.coedge)
        exporter.write_ptr(self.face)


@register
class Coedge(SupportsPattern):
    type: str = "coedge"
    next_coedge: Coedge = NONE_REF
    prev_coedge: Coedge = NONE_REF
    partner_coedge: Coedge = NONE_REF
    edge: Edge = NONE_REF
    # sense: True = reversed; False = forward;
    # coedge has the same direction as the underlying edge
    sense: bool = True
    loop: Loop = NONE_REF  # parent/owner
    unknown: int = 0  # only in SAB file!?
    pcurve: PCurve = NONE_REF

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.next_coedge = restore_entity("coedge", loader, entity_factory)
        self.prev_coedge = restore_entity("coedge", loader, entity_factory)
        self.partner_coedge = restore_entity("coedge", loader, entity_factory)
        self.edge = restore_entity("edge", loader, entity_factory)
        self.sense = loader.read_bool("reversed", "forward")
        self.loop = restore_entity("loop", loader, entity_factory)
        self.unknown = loader.read_int(skip_sat=0)
        self.pcurve = restore_entity("pcurve", loader, entity_factory)

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_ptr(self.next_coedge)
        exporter.write_ptr(self.prev_coedge)
        exporter.write_ptr(self.partner_coedge)
        exporter.write_ptr(self.edge)
        exporter.write_bool(self.sense, "reversed", "forward")
        exporter.write_ptr(self.loop)
        # TODO: write_int() ?
        exporter.write_int(0, skip_sat=True)
        exporter.write_ptr(self.pcurve)


@register
class Edge(SupportsPattern):
    type: str = "edge"
    start_vertex: Vertex = NONE_REF
    start_param: float = 0.0
    end_vertex: Vertex = NONE_REF
    end_param: float = 0.0
    coedge: Coedge = NONE_REF
    curve: Curve = NONE_REF
    # sense: True = reversed; False = forward;
    # edge has the same direction as the underlying curve
    sense: bool = True
    convexity: str = "unknown"

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.start_vertex = restore_entity("vertex", loader, entity_factory)
        if loader.version >= Features.TOL_MODELING:
            self.start_param = loader.read_double()
        self.end_vertex = restore_entity("vertex", loader, entity_factory)
        if loader.version >= Features.TOL_MODELING:
            self.end_param = loader.read_double()
        self.coedge = restore_entity("coedge", loader, entity_factory)
        self.curve = restore_entity("curve", loader, entity_factory)
        self.sense = loader.read_bool("reversed", "forward")
        if loader.version >= Features.TOL_MODELING:
            self.convexity = loader.read_str()

    def write_common(self, exporter: DataExporter) -> None:
        # write support >= version 700 only
        super().write_common(exporter)
        exporter.write_ptr(self.start_vertex)
        exporter.write_double(self.start_param)
        exporter.write_ptr(self.end_vertex)
        exporter.write_double(self.end_param)
        exporter.write_ptr(self.coedge)
        exporter.write_ptr(self.curve)
        exporter.write_bool(self.sense, "reversed", "forward")
        exporter.write_str(self.convexity)


@register
class PCurve(SupportsPattern):  # not implemented
    type: str = "pcurve"


@register
class Vertex(SupportsPattern):
    type: str = "vertex"
    edge: Edge = NONE_REF
    unknown: int = 0  # only in SAB files, reference counter?
    point: Point = NONE_REF

    def restore_common(
        self, loader: DataLoader, entity_factory: Factory
    ) -> None:
        super().restore_common(loader, entity_factory)
        self.edge = restore_entity("edge", loader, entity_factory)
        self.unknown = loader.read_int(skip_sat=0)
        self.point = restore_entity("point", loader, entity_factory)

    def write_common(self, exporter: DataExporter) -> None:
        super().write_common(exporter)
        exporter.write_ptr(self.edge)
        # TODO: write_int() ?
        exporter.write_int(0, skip_sat=True)
        exporter.write_ptr(self.point)


@register
class Curve(SupportsPattern):
    type: str = "curve"
    bounds = INF, INF

    def restore_data(self, loader: DataLoader) -> None:
        self.bounds = loader.read_interval(), loader.read_interval()

    def write_data(self, exporter: DataExporter) -> None:
        exporter.write_interval(self.bounds[0])
        exporter.write_interval(self.bounds[1])


@register
class StraightCurve(Curve):
    type: str = "straight-curve"
    origin = Vec3(0, 0, 0)
    direction = Vec3(1, 0, 0)

    def restore_data(self, loader: DataLoader) -> None:
        self.origin = Vec3(loader.read_vec3())
        self.direction = Vec3(loader.read_vec3())
        super().restore_data(loader)

    def write_data(self, exporter: DataExporter) -> None:
        exporter.write_loc_vec3(self.origin)
        exporter.write_dir_vec3(self.direction)
        super().write_data(exporter)


@register
class Point(SupportsPattern):
    type: str = "point"
    location: Vec3 = NULLVEC

    def restore_data(self, loader: DataLoader) -> None:
        self.location = Vec3(loader.read_vec3())

    def write_data(self, exporter: DataExporter) -> None:
        exporter.write_loc_vec3(self.location)


class FileLoader(abc.ABC):
    records: Sequence[Union[sat.SatEntity, sab.SabEntity]]

    def __init__(self, version: int):
        self.entities: Dict[int, AcisEntity] = {}
        self.version: int = version

    def entity_factory(self, raw_entity: AbstractEntity) -> AcisEntity:
        uid = id(raw_entity)
        try:
            return self.entities[uid]
        except KeyError:  # create a new entity
            entity = ENTITY_TYPES.get(raw_entity.name, AcisEntity)()
            self.entities[uid] = entity
            return entity

    def bodies(self) -> List[Body]:
        # noinspection PyTypeChecker
        return [e for e in self.entities.values() if isinstance(e, Body)]

    def load_entities(self):
        entity_factory = self.entity_factory

        for raw_entity in self.records:
            entity = entity_factory(raw_entity)
            entity.id = raw_entity.id
            attributes = raw_entity.attributes
            if not attributes.is_null_ptr:
                entity.attributes = entity_factory(attributes)
            data_loader = self.make_data_loader(raw_entity.data)
            entity.load(data_loader, entity_factory)

    @abc.abstractmethod
    def make_data_loader(self, data: List[Any]) -> DataLoader:
        pass


class SabLoader(FileLoader):
    def __init__(self, data: Union[bytes, bytearray, Sequence[bytes]]):
        builder = sab.parse_sab(data)
        super().__init__(builder.header.version)
        self.records = builder.entities

    def make_data_loader(self, data: List[Any]) -> DataLoader:
        return sab.SabDataLoader(data, self.version)

    @classmethod
    def load(cls, data: Union[bytes, bytearray, Sequence[bytes]]) -> List[Body]:
        loader = cls(data)
        loader.load_entities()
        return loader.bodies()


class SatLoader(FileLoader):
    def __init__(self, data: Union[str, Sequence[str]]):
        builder = sat.parse_sat(data)
        super().__init__(builder.header.version)
        self.records = builder.entities

    def make_data_loader(self, data: List[Any]) -> DataLoader:
        return sat.SatDataLoader(data, self.version)

    @classmethod
    def load(cls, data: Union[str, Sequence[str]]) -> List[Body]:
        loader = cls(data)
        loader.load_entities()
        return loader.bodies()