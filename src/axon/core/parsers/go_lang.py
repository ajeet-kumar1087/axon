"""Go language parser using tree-sitter.

Extracts functions, methods, structs (as classes), interfaces, imports,
and calls from Go source code.
"""

from __future__ import annotations

import tree_sitter_go as tsgo
from tree_sitter import Language, Node, Parser

from axon.core.parsers.base import (
    CallInfo,
    ImportInfo,
    LanguageParser,
    ParseResult,
    SymbolInfo,
    TypeRef,
)

GO_LANGUAGE = Language(tsgo.language())

_BUILTIN_TYPES: frozenset[str] = frozenset(
    {
        "string", "int", "int8", "int16", "int32", "int64",
        "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
        "byte", "rune", "float32", "float64", "complex64", "complex128",
        "bool", "error", "any", "interface{}", "map", "slice", "chan",
    }
)

class GoParser(LanguageParser):
    """Parses Go source code using tree-sitter."""

    def __init__(self) -> None:
        self._parser = Parser(GO_LANGUAGE)

    def parse(self, content: str, file_path: str) -> ParseResult:
        """Parse Go source and return structured information."""
        tree = self._parser.parse(bytes(content, "utf8"))
        result = ParseResult()
        root = tree.root_node
        self._walk(root, content, result)
        return result

    def _walk(self, node: Node, content: str, result: ParseResult) -> None:
        """Recursively walk the AST to extract definitions."""
        ntype = node.type

        if ntype == "function_declaration":
            self._extract_function(node, content, result)
        elif ntype == "method_declaration":
            self._extract_method(node, content, result)
        elif ntype == "type_declaration":
            self._extract_type_declaration(node, content, result)
        elif ntype == "import_declaration":
            self._extract_imports(node, content, result)
        elif ntype == "call_expression":
            self._extract_call(node, content, result)

        for child in node.children:
            self._walk(child, content, result)

    def _extract_function(self, node: Node, content: str, result: ParseResult) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = name_node.text.decode("utf8")
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        node_content = node.text.decode("utf8")

        result.symbols.append(
            SymbolInfo(
                name=name,
                kind="function",
                start_line=start_line,
                end_line=end_line,
                content=node_content,
                signature=self._build_signature(node),
            )
        )
        
        # Check if exported (starts with uppercase)
        if name[0].isupper():
            result.exports.append(name)

    def _extract_method(self, node: Node, content: str, result: ParseResult) -> None:
        name_node = node.child_by_field_name("name")
        receiver_node = node.child_by_field_name("receiver")
        if name_node is None:
            return

        name = name_node.text.decode("utf8")
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        node_content = node.text.decode("utf8")

        class_name = ""
        if receiver_node:
            # receiver is usually (r *ReceiverType) or (r ReceiverType)
            # We want the type name.
            for child in receiver_node.children:
                if child.type == "parameter_declaration":
                    type_node = child.child_by_field_name("type")
                    if type_node:
                        class_name = self._extract_type_name(type_node)
                        break

        result.symbols.append(
            SymbolInfo(
                name=name,
                kind="method",
                start_line=start_line,
                end_line=end_line,
                content=node_content,
                signature=self._build_signature(node),
                class_name=class_name,
            )
        )

        if name[0].isupper():
            result.exports.append(name)

    def _extract_type_declaration(self, node: Node, content: str, result: ParseResult) -> None:
        # type_declaration -> type_spec
        for spec in node.children:
            if spec.type == "type_spec":
                name_node = spec.child_by_field_name("name")
                type_node = spec.child_by_field_name("type")
                if name_node and type_node:
                    name = name_node.text.decode("utf8")
                    kind = "class" if type_node.type == "struct_type" else "interface"
                    if type_node.type not in ("struct_type", "interface_type"):
                        kind = "type_alias"

                    result.symbols.append(
                        SymbolInfo(
                            name=name,
                            kind=kind,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            content=node.text.decode("utf8"),
                        )
                    )
                    if name[0].isupper():
                        result.exports.append(name)

    def _extract_imports(self, node: Node, content: str, result: ParseResult) -> None:
        # import "fmt" or import ( "fmt"; "os" )
        for child in node.children:
            if child.type == "import_spec":
                path_node = child.child_by_field_name("path")
                alias_node = child.child_by_field_name("name")
                if path_node:
                    path = path_node.text.decode("utf8").strip('"')
                    alias = alias_node.text.decode("utf8") if alias_node else ""
                    result.imports.append(
                        ImportInfo(
                            module=path,
                            names=[path.split("/")[-1]],
                            alias=alias,
                        )
                    )

    def _extract_call(self, node: Node, content: str, result: ParseResult) -> None:
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return

        line = node.start_point[0] + 1
        
        if func_node.type == "selector_expression":
            # receiver.Method()
            operand = func_node.child_by_field_name("operand")
            field = func_node.child_by_field_name("field")
            if field:
                result.calls.append(
                    CallInfo(
                        name=field.text.decode("utf8"),
                        line=line,
                        receiver=operand.text.decode("utf8") if operand else "",
                    )
                )
        elif func_node.type == "identifier":
            result.calls.append(
                CallInfo(
                    name=func_node.text.decode("utf8"),
                    line=line,
                )
            )

    def _extract_type_name(self, node: Node) -> str:
        """Extract simple type name, handling pointers."""
        if node.type == "pointer_type":
            for child in node.children:
                if child.is_named:
                    return self._extract_type_name(child)
        return node.text.decode("utf8")

    def _build_signature(self, node: Node) -> str:
        # Simplified signature: func [receiver] name(params) [results]
        return node.text.decode("utf8").split("{")[0].strip()
