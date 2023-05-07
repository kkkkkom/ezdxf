#  Copyright (c) 2023, Manfred Moitzi
#  License: MIT License
from __future__ import annotations
from typing import Iterable, Sequence, no_type_check, NamedTuple
from typing_extensions import Self
import math
import itertools
import dataclasses
from xml.etree import ElementTree as ET

from ezdxf.math import AnyVec, Vec2, BoundingBox2d, Matrix44
from ezdxf.path import Path, Path2d, Command

from .type_hints import Color
from .backend import BackendInterface
from .config import Configuration
from .properties import BackendProperties
from .recorder import Recorder

CMD_M_ABS = "M {0.x:.0f} {0.y:.0f}"
CMD_M_REL = "m {0.x:.0f} {0.y:.0f}"
CMD_L_ABS = "L {0.x:.0f} {0.y:.0f}"
CMD_L_REL = "l {0.x:.0f} {0.y:.0f}"
CMD_C3_ABS = "Q {0.x:.0f} {0.y:.0f} {1.x:.0f} {1.y:.0f}"
CMD_C3_REL = "q {0.x:.0f} {0.y:.0f} {1.x:.0f} {1.y:.0f}"
CMD_C4_ABS = "C {0.x:.0f} {0.y:.0f} {1.x:.0f} {1.y:.0f} {2.x:.0f} {2.y:.0f}"
CMD_C4_REL = "c {0.x:.0f} {0.y:.0f} {1.x:.0f} {1.y:.0f} {2.x:.0f} {2.y:.0f}"
CMD_CONT = "{0.x:.0f} {0.y:.0f}"

__all__ = ["SVGBackend", "Settings"]

CSS_UNITS_TO_MM = {
    "cm": 10.0,
    "mm": 1.0,
    "in": 25.4,
    "px": 25.4 / 96.0,
    "pt": 25.4 / 72.0,
}

# all page sizes in landscape orientation
PAGE_SIZES = {
    "ISO A0": (1189, 841, "mm"),
    "ISO A1": (841, 594, "mm"),
    "ISO A2": (594, 420, "mm"),
    "ISO A3": (420, 297, "mm"),
    "ISO A4": (297, 210, "mm"),
    "ANSI A": (11, 8.5, "in"),
    "ANSI B": (17, 11, "in"),
    "ANSI C": (22, 17, "in"),
    "ANSI D": (34, 22, "in"),
    "ANSI E": (44, 34, "in"),
    "ARCH C": (24, 18, "in"),
    "ARCH D": (36, 24, "in"),
    "ARCH E": (48, 36, "in"),
    "ARCH E1": (42, 30, "in"),
    "Letter": (11, 8.5, "in"),
    "Legal": (14, 8.5, "in"),
}
MAX_VIEW_BOX_COORDS = 100_000


class Margins(NamedTuple):
    """Page margins definition class"""

    top: float
    right: float
    bottom: float
    left: float

    @classmethod
    def uniform4(cls, margin: float) -> Self:
        """Returns a page margins definition class with four equal margins."""
        return cls(margin, margin, margin, margin)

    @classmethod
    def uniform2(cls, top_bottom: float, left_right: float) -> Self:
        """Returns a page margins definition class with equal top-bottom and
        left-right margins.
        """
        return cls(top_bottom, left_right, top_bottom, left_right)

    def scale(self, factor: float) -> Self:
        return self.__class__(
            self.top * factor,
            self.right * factor,
            self.bottom * factor,
            self.left * factor,
        )


@dataclasses.dataclass
class Page:
    """Page definition class"""

    width: float
    height: float
    units: str = "mm"
    margins: Margins = Margins.uniform4(0)

    def __post_init__(self):
        if self.units not in CSS_UNITS_TO_MM:
            raise ValueError(f"unsupported or invalid units: {self.units}")

    @property
    def width_in_mm(self) -> int:
        return round(self.width * CSS_UNITS_TO_MM[self.units])

    @property
    def height_in_mm(self) -> int:
        return round(self.height * CSS_UNITS_TO_MM[self.units])

    @property
    def margins_in_mm(self) -> Margins:
        return self.margins.scale(CSS_UNITS_TO_MM[self.units])

    def to_landscape(self) -> None:
        if self.width < self.height:
            self.width, self.height = self.height, self.width

    def to_portrait(self) -> None:
        if self.height < self.width:
            self.width, self.height = self.height, self.width


@dataclasses.dataclass
class Settings:
    # Preserves the aspect-ratio at all scaling operations, these are CAD drawings!
    #
    # rotate content about 0, 90,  180 or 270 degrees
    content_rotation: int = 0

    # Scale content to fit the page,
    fit_page: bool = True

    # If the content shouldn't be scaled to fit the page, how much input units, which
    # are the DXF drawing units in model- or paper space, represent 1 mm in the rendered
    # SVG drawing.
    # e.g. scale 1:100 for input unit is 1m, so 0.01 input units is 1mm in the SVG drawing
    # or 1000mm in input units corresponds to 10mm in the SVG drawing = 10 / 1000 = 0.01;
    # e.g. scale 1:1; input unit is 1mm = 1 / 1 = 1.0 the default value
    # This value is ignored if fit_page is True!
    input_units_in_mm: float = 1.0

    def __post_init__(self) -> None:
        if self.content_rotation not in (0, 90, 180, 270):
            raise ValueError(
                f"invalid content rotation {self.content_rotation}, valid: 0, 90, 180, 270"
            )


class SVGBackend(Recorder):
    def __init__(self) -> None:
        super().__init__()
        self._init_y_axis_flip = True

    def get_string(self, page: Page, settings=Settings()) -> str:
        # The SVG coordinate system has an inverted y-axis in comparison to the DXF
        # coordinate system, flip y-axis at the first transformation:
        flip_y = -1.0 if self._init_y_axis_flip else 1.0
        rotation = settings.content_rotation
        if rotation not in (0, 90, 180, 270):
            raise ValueError("content rotation must be 0, 90, 180 or 270 degrees")
        bbox = self.bbox()

        # the output coordinates are integer values in the range [0, MAX_VIEW_BOX_COORDS]
        scale = scale_view_box(bbox, page)
        m = placement_matrix(
            bbox,
            sx=scale,
            sy=scale * flip_y,
            rotation=rotation,
            margin_left=page.margins.left / page.width,  # as percentage of page width
            margin_bottom=page.margins.bottom
            / page.height,  # as percentage of page height
        )
        self.transform(m)
        self._init_y_axis_flip = False

        # bounding box after transformation!
        box = self.bbox()
        view_box_width, view_box_height = make_view_box(page)
        backend = SVGRenderBackend(view_box_width, view_box_height, page)
        self.replay(backend)
        return backend.get_string()


def make_view_box(page: Page) -> tuple[int, int]:
    if page.width > page.height:
        return MAX_VIEW_BOX_COORDS, round(
            MAX_VIEW_BOX_COORDS * (page.height / page.width)
        )
    return round(MAX_VIEW_BOX_COORDS * (page.width / page.height)), MAX_VIEW_BOX_COORDS


def scale_view_box(bbox: BoundingBox2d, page: Page) -> int:
    # The viewBox coordinates are integer values in the range of [0, MAX_VIEW_BOX_COORDS]
    horiz_margin_factor = (page.margins.left + page.margins.right) / page.width
    vert_margin_factor = (page.margins.top + page.margins.bottom) / page.width
    scale_content_x = 1.0 + horiz_margin_factor
    scale_content_y = 1.0 + vert_margin_factor
    return round(
        min(
            MAX_VIEW_BOX_COORDS / (bbox.size.x * scale_content_x),
            MAX_VIEW_BOX_COORDS / (bbox.size.y * scale_content_y),
        )
    )


def placement_matrix(
    bbox: BoundingBox2d,
    sx: float = 1.0,
    sy: float = 1.0,
    rotation: float = 0.0,
    margin_left: float = 0.0,
    margin_bottom: float = 0.0,
) -> Matrix44:
    """Returns a matrix to place the bbox in the first quadrant of the coordinate
    system (+x, +y).
    """
    if abs(sx) < 1e-9:
        sx = 1.0
    if abs(sy) < 1e-9:
        sy = 1.0
    m = Matrix44.scale(sx, sy, 1.0)
    if rotation:
        m @= Matrix44.z_rotate(math.radians(rotation))
    corners = m.transform_vertices(bbox.rect_vertices())
    # final output canvas
    canvas = BoundingBox2d(corners)
    # calculate margin offset
    mx = canvas.size.x * margin_left
    my = canvas.size.y * margin_bottom
    tx, ty = canvas.extmin  # type: ignore
    return m @ Matrix44.translate(mx - tx, my - ty, 0)


class SVGRenderBackend(BackendInterface):
    """Creates the SVG output.

    This backend requires some preliminary work, record the frontend output via the
    Recorder backend to accomplish the following requirements:

    - Scale the content in y-axis by -1 to invert the y-axis (SVG).
    - Move content in the first quadrant of the coordinate system.
    - The viewBox is defined by the lower left corner in the origin (0, 0) and
      the upper right corner at (view_box_width, view_box_height)
    - The output coordinates are integer values, scale the content appropriately.
    - Replay the recorded output at this backend.

    """

    def __init__(self, view_box_width: int, view_box_height: int, page: Page) -> None:
        self.stroke_width: float = view_box_width / page.width_in_mm
        self.root = ET.Element(
            "svg",
            xmlns="http://www.w3.org/2000/svg",
            width=f"{page.width}{page.units}",
            height=f"{page.height}{page.units}",
            viewBox=f"0 0 {view_box_width} {view_box_height}",
        )
        self.background = ET.SubElement(
            self.root,
            "rect",
            fill="white",
            x="0",
            y="0",
            width=str(view_box_width),
            height=str(view_box_height),
        )
        self.fillings = ET.SubElement(self.root, "g", stroke="none", fill="black")
        self.fillings.set("fill-rule", "evenodd")
        self.strokes = ET.SubElement(self.root, "g", stroke="black", fill="none")
        self.strokes.set("stroke-linecap", "round")
        self.strokes.set("stroke-linejoin", "round")

    def get_string(self) -> str:
        return ET.tostring(self.root, encoding="unicode", xml_declaration=True)

    def set_background(self, color: Color) -> None:
        self.background.set("fill", color)

    def set_line_properties(
        self, element: ET.Element, properties: BackendProperties
    ) -> None:
        element.set("stroke", properties.color)
        element.set("stroke-width", f"{properties.lineweight*self.stroke_width:.0f}")

    def set_fill_properties(
        self, element: ET.Element, properties: BackendProperties
    ) -> None:
        element.set("fill", properties.color)

    def draw_point(self, pos: AnyVec, properties: BackendProperties) -> None:
        d = self.make_polyline_str([pos, pos])
        if d:
            element = ET.SubElement(self.strokes, "path", d=d)
            self.set_line_properties(element, properties)

    def draw_line(
        self, start: AnyVec, end: AnyVec, properties: BackendProperties
    ) -> None:
        d = self.make_polyline_str([start, end])
        if d:
            element = ET.SubElement(self.strokes, "path", d=d)
            self.set_line_properties(element, properties)

    def draw_solid_lines(
        self, lines: Iterable[tuple[AnyVec, AnyVec]], properties: BackendProperties
    ) -> None:
        lines = list(lines)
        if len(lines) == 0:
            return
        element = ET.SubElement(self.strokes, "path", d=self.make_multi_line_str(lines))
        self.set_line_properties(element, properties)

    def draw_path(self, path: Path | Path2d, properties: BackendProperties) -> None:
        d = self.make_path_str(path)
        if d:
            element = ET.SubElement(self.strokes, "path", d=d)
            self.set_line_properties(element, properties)

    def draw_filled_paths(
        self,
        paths: Iterable[Path | Path2d],
        holes: Iterable[Path | Path2d],
        properties: BackendProperties,
    ) -> None:
        d = []
        for path in itertools.chain(paths, holes):
            if len(path):
                d.append(self.make_path_str(path, close=True))
        element = ET.SubElement(self.fillings, "path", d=" ".join(d))
        self.set_fill_properties(element, properties)

    def draw_filled_polygon(
        self, points: Iterable[AnyVec], properties: BackendProperties
    ) -> None:
        s = self.make_polyline_str(list(points), close=True)
        if not s:
            return
        element = ET.SubElement(self.fillings, "path", d=s)
        self.set_fill_properties(element, properties)

    def make_polyline_str(self, points: Sequence[Vec2], close=False) -> str:
        if len(points) < 2:
            return ""
        current = points[0]
        # first move is absolute, consecutive lines are relative:
        d: list[str] = [CMD_M_ABS.format(current), "l"]
        for point in points[1:]:
            relative = point - current
            current = point
            d.append(CMD_CONT.format(relative))
        if close:
            d.append("Z")
        return " ".join(d)

    def make_multi_line_str(self, lines: Sequence[tuple[Vec2, Vec2]]) -> str:
        assert len(lines) > 0
        start, end = lines[0]
        d: list[str] = [CMD_M_ABS.format(start), CMD_L_REL.format(end - start)]
        current = end
        for start, end in lines[1:]:
            d.append(CMD_M_REL.format(start - current))
            current = start
            d.append(CMD_L_REL.format(end - current))
            current = end
        return " ".join(d)

    @no_type_check
    def make_path_str(self, path: Path | Path2d, close=False) -> str:
        d: list[str] = [CMD_M_ABS.format(path.start)]
        if len(path) == 0:
            return ""

        current = path.start
        for cmd in path.commands():
            end = cmd.end
            if cmd.type == Command.MOVE_TO:
                d.append(CMD_M_REL.format(end - current))
            elif cmd.type == Command.LINE_TO:
                d.append(CMD_L_REL.format(end - current))
            elif cmd.type == Command.CURVE3_TO:
                d.append(CMD_C3_REL.format(cmd.ctrl - current, end - current))
            elif cmd.type == Command.CURVE4_TO:
                d.append(
                    CMD_C4_REL.format(
                        cmd.ctrl1 - current, cmd.ctrl2 - current, end - current
                    )
                )
            current = end
        if close:
            d.append("Z")

        return " ".join(d)

    def configure(self, config: Configuration) -> None:
        pass

    def clear(self) -> None:
        pass

    def finalize(self) -> None:
        pass

    def enter_entity(self, entity, properties) -> None:
        pass

    def exit_entity(self, entity) -> None:
        pass
