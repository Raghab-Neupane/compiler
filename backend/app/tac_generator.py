import ast
import re
from typing import Any, Optional, Union


C_ASSIGNMENT = re.compile(
    r"^\s*(?P<declaration>(?:(?:const|unsigned|signed|long|short|int|float|double|char)\s+)+)?"
    r"(?P<target>[A-Za-z_]\w*)\s*=\s*(?P<expression>.*?)\s*$"
)
C_SIMPLE_EXPRESSION = re.compile(
    r"^(?:[A-Za-z_]\w*|-?\d+)(?:\s*[+\-*/%]\s*(?:[A-Za-z_]\w*|-?\d+))*$"
)
C_LEADING_COMMENTS = re.compile(r"(?:\s|//[^\n]*|/\*.*?\*/)*", re.DOTALL)
C_TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<line_comment>//[^\n]*)|(?P<block_comment>/\*.*?\*/)"
    r"|(?P<directive>^[ \t]*\#[^\n]*)|(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    r"|(?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|(?P<identifier>[A-Za-z_]\w*)"
    r"|(?P<operator>\+\+|--|\+=|-=|\*=|/=|%=|==|!=|<=|>=|&&|\|\||<<|>>|->)"
    r"|(?P<punctuation>[{}()\[\],;?:.+\-*/%<>=!&|])",
    re.MULTILINE | re.DOTALL,
)


class TacGenerationError(ValueError):
    pass


class _CTacParser:
    _types = {
        "void", "char", "short", "int", "long", "float", "double", "signed",
        "unsigned", "_Bool", "bool", "const", "volatile", "static", "register",
        "extern", "struct", "enum",
    }
    _precedence = {
        "=": 1, "+=": 1, "-=": 1, "*=": 1, "/=": 1, "%=": 1,
        "||": 2, "&&": 3, "==": 4, "!=": 4,
        "<": 5, "<=": 5, ">": 5, ">=": 5,
        "+": 6, "-": 6, "*": 7, "/": 7, "%": 7,
    }

    def __init__(self, source: str):
        self.source = source
        self.tokens: list[tuple[str, int]] = []
        self.constants: dict[str, int] = {}
        self.instructions: list[dict[str, Union[int, str]]] = []
        for line_number, line in enumerate(source.splitlines(), start=1):
            if not re.match(r"^\s*#\s*define\b", line):
                continue
            definition = re.match(
                r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+\(?(-?\d+)\)?\s*(?://.*|/\*.*\*/\s*)?$",
                line,
            )
            if not definition:
                raise TacGenerationError(
                    f"Unsupported preprocessor definition at line {line_number}; "
                    "TAC generation supports integer #define values."
                )
            name, value = definition.groups()
            self.constants[name] = int(value)
            self.instructions.append(
                {"source_line": line_number, "instruction": f"const {name} = {value}"}
            )
        previous_end = 0
        for match in C_TOKEN.finditer(source):
            kind = match.lastgroup
            skipped = source[previous_end : match.start()]
            if skipped.strip():
                line = source.count("\n", 0, previous_end) + 1
                raise TacGenerationError(
                    f"Unsupported C syntax at line {line}: {skipped.strip()[:24]!r}."
                )
            previous_end = match.end()
            if kind in {"space", "line_comment", "block_comment", "directive"}:
                continue
            self.tokens.append((match.group(), source.count("\n", 0, match.start()) + 1))
        if source[previous_end:].strip():
            line = source.count("\n", 0, previous_end) + 1
            raise TacGenerationError(
                f"Unsupported C syntax at line {line}: {source[previous_end:].strip()[:24]!r}."
            )
        self.tokens.append(("<eof>", source.count("\n") + 1))
        self.position = 0
        self.temporary = 0
        self.label = 0
        self.array_dimensions: dict[str, list[str]] = {}
        self.loop_stack: list[tuple[str, str]] = []

    @property
    def token(self) -> str:
        return self.tokens[self.position][0]

    @property
    def line(self) -> int:
        return self.tokens[self.position][1]

    def peek(self, distance: int = 1) -> str:
        return self.tokens[min(self.position + distance, len(self.tokens) - 1)][0]

    def take(self, expected: Optional[str] = None) -> str:
        value, line = self.tokens[self.position]
        if expected is not None and value != expected:
            raise TacGenerationError(
                f"Unsupported C syntax at line {line}: expected '{expected}', found '{value}'."
            )
        self.position += 1
        return value

    def emit(self, instruction: str, line: Optional[int] = None) -> None:
        self.instructions.append(
            {"source_line": line if line is not None else self.line, "instruction": instruction}
        )

    def new_temp(self) -> str:
        self.temporary += 1
        return f"t{self.temporary}"

    def new_label(self, prefix: str) -> str:
        self.label += 1
        return f"{prefix}_{self.label}"

    def parse(self) -> list[dict[str, Union[int, str]]]:
        while self.token != "<eof>":
            if self.token == ";":
                self.take(";")
            elif self.token in self._types:
                self.parse_external_declaration()
            elif self.token == "}":
                raise TacGenerationError(f"Unexpected '}}' at line {self.line}.")
            elif self.token.isidentifier():
                self.parse_function_or_statement()
            else:
                raise TacGenerationError(
                    f"Unsupported C syntax at line {self.line}: '{self.token}'."
                )
        return self.instructions

    def parse_external_declaration(self) -> None:
        start = self.position
        while self.tokens[self.position][0] in self._types:
            self.position += 1
        name_position = self.position
        if (
            self.tokens[name_position][0].isidentifier()
            and self.tokens[min(name_position + 1, len(self.tokens) - 1)][0] == "("
        ):
            self.position = name_position
            self.parse_function()
        else:
            self.position = start
            self.parse_declaration(global_scope=True)

    def parse_function(self) -> None:
        function_name = self.take()
        line = self.tokens[self.position - 1][1]
        self.take("(")
        depth = 1
        while depth and self.token != "<eof>":
            if self.token == "(":
                depth += 1
            elif self.token == ")":
                depth -= 1
            self.take()
        if depth:
            raise TacGenerationError(f"Unclosed function parameter list near line {line}.")
        if self.token == ";":
            self.take(";")
            return
        self.emit(f"function {function_name}:", line)
        self.parse_block()
        self.emit(f"end function {function_name}", line)

    def parse_block(self) -> None:
        self.take("{")
        while self.token not in {"}", "<eof>"}:
            self.parse_statement()
        self.take("}")

    def parse_statement(self) -> None:
        if self.token == "{":
            self.parse_block()
        elif self.token in self._types:
            self.parse_declaration()
        elif self.token == "for":
            self.parse_for()
        elif self.token == "while":
            self.parse_while()
        elif self.token == "do":
            self.parse_do_while()
        elif self.token == "if":
            self.parse_if()
        elif self.token == "return":
            line = self.take_line()
            value = ""
            if self.token != ";":
                value = self.parse_expression()
            self.take(";")
            self.emit(f"return {value}".rstrip(), line)
        elif self.token == "break":
            line = self.take_line()
            if not self.loop_stack:
                raise TacGenerationError(f"'break' outside a loop at line {line}.")
            self.take(";")
            self.emit(f"goto {self.loop_stack[-1][1]}", line)
        elif self.token == "continue":
            line = self.take_line()
            if not self.loop_stack:
                raise TacGenerationError(f"'continue' outside a loop at line {line}.")
            self.take(";")
            self.emit(f"goto {self.loop_stack[-1][0]}", line)
        elif self.token == ";":
            self.take(";")
        else:
            line = self.line
            instruction_count = len(self.instructions)
            expression = self.parse_expression()
            self.take(";")
            if expression and len(self.instructions) == instruction_count:
                self.emit(f"eval {expression}", line)

    def take_line(self) -> int:
        line = self.line
        self.take()
        return line

    def parse_declaration(self, global_scope: bool = False) -> None:
        line = self.line
        type_tokens: list[str] = []
        while self.token in self._types:
            type_tokens.append(self.take())
            if type_tokens[-1] in {"struct", "enum"}:
                type_tokens.append(self.take())
        type_name = " ".join(type_tokens)
        while True:
            while self.token in {"*", "const"}:
                type_name += self.take()
            name = self.take()
            if not name.isidentifier():
                raise TacGenerationError(f"Expected a declaration name at line {self.line}.")
            dimensions: list[str] = []
            while self.token == "[":
                self.take("[")
                dimensions.append(self.parse_expression())
                self.take("]")
            declaration_line = self.line
            self.emit(
                f"decl {type_name} {name}"
                + "".join(f"[{dimension}]" for dimension in dimensions),
                line,
            )
            if dimensions:
                self.array_dimensions[name] = dimensions
            if self.token == "=":
                self.take("=")
                if self.token == "{":
                    self.parse_array_initializer(name, dimensions, 0, line)
                else:
                    value = self.parse_expression()
                    self.emit(f"{name} = {value}", declaration_line)
            if self.token != ",":
                break
            self.take(",")
        if not global_scope:
            self.take(";")
        elif self.token == ";":
            self.take(";")
        else:
            raise TacGenerationError(f"Expected ';' after declaration at line {self.line}.")

    def parse_array_initializer(
        self, name: str, dimensions: list[str], offset: int, declaration_line: int
    ) -> int:
        values: list[tuple[str, int]] = []

        def read_values() -> None:
            self.take("{")
            while self.token not in {"}", "<eof>"}:
                if self.token == "{":
                    read_values()
                else:
                    value_line = self.line
                    values.append((self.parse_expression(), value_line))
                if self.token != ",":
                    break
                self.take(",")
            self.take("}")

        read_values()
        try:
            element_count = 1
            for dimension in dimensions:
                element_count *= self.constant_value(dimension)
        except ValueError as exc:
            raise TacGenerationError(
                f"Array initializer for '{name}' needs constant dimensions."
            ) from exc

        for index, (value, value_line) in enumerate(values[:element_count]):
            self.emit(f"{name}[{offset + index}] = {value}", value_line)
        for index in range(len(values), element_count):
            self.emit(f"{name}[{offset + index}] = 0", declaration_line)
        return min(len(values), element_count)

    def parse_for(self) -> None:
        line = self.take_line()
        self.take("(")
        if self.token in self._types:
            self.parse_declaration()
        elif self.token != ";":
            self.parse_expression()
            self.take(";")
        else:
            self.take(";")

        condition_label = self.new_label("for_cond")
        increment_label = self.new_label("for_increment")
        end_label = self.new_label("for_end")
        self.emit(f"label {condition_label}", line)
        condition_line = self.line
        condition = self.parse_expression() if self.token != ";" else "1"
        self.take(";")

        outer = self.instructions
        self.instructions = []
        if self.token != ")":
            increment = self.parse_expression()
        else:
            increment = ""
        self.take(")")
        increment_instructions = self.instructions
        self.instructions = outer

        if condition != "1":
            self.emit(f"ifFalse {condition} goto {end_label}", condition_line)
        self.loop_stack.append((increment_label, end_label))
        self.parse_statement()
        self.loop_stack.pop()
        self.emit(f"label {increment_label}", line)
        self.instructions.extend(increment_instructions)
        if increment and not increment_instructions:
            self.emit(increment, line)
        self.emit(f"goto {condition_label}", line)
        self.emit(f"label {end_label}", line)

    def parse_while(self) -> None:
        line = self.take_line()
        condition_label = self.new_label("while_cond")
        end_label = self.new_label("while_end")
        self.emit(f"label {condition_label}", line)
        self.take("(")
        condition = self.parse_expression()
        self.take(")")
        self.emit(f"ifFalse {condition} goto {end_label}", line)
        self.loop_stack.append((condition_label, end_label))
        self.parse_statement()
        self.loop_stack.pop()
        self.emit(f"goto {condition_label}", line)
        self.emit(f"label {end_label}", line)

    def parse_do_while(self) -> None:
        line = self.take_line()
        body_label = self.new_label("do_body")
        condition_label = self.new_label("do_cond")
        end_label = self.new_label("do_end")
        self.emit(f"label {body_label}", line)
        self.loop_stack.append((condition_label, end_label))
        self.parse_statement()
        self.loop_stack.pop()
        self.emit(f"label {condition_label}", line)
        self.take("while")
        self.take("(")
        condition = self.parse_expression()
        self.take(")")
        self.take(";")
        self.emit(f"if {condition} goto {body_label}", line)
        self.emit(f"label {end_label}", line)

    def parse_if(self) -> None:
        line = self.take_line()
        self.take("(")
        condition = self.parse_expression()
        self.take(")")
        else_label = self.new_label("if_else")
        end_label = self.new_label("if_end")
        self.emit(f"ifFalse {condition} goto {else_label}", line)
        self.parse_statement()
        if self.token == "else":
            self.emit(f"goto {end_label}", line)
            self.emit(f"label {else_label}", line)
            self.take("else")
            self.parse_statement()
            self.emit(f"label {end_label}", line)
        else:
            self.emit(f"label {else_label}", line)

    def parse_expression(self, minimum_precedence: int = 1) -> str:
        line = self.line
        left = self.parse_unary()
        while self.token in self._precedence and self._precedence[self.token] >= minimum_precedence:
            operator = self.take()
            precedence = self._precedence[operator]
            right = self.parse_expression(precedence + (0 if operator.endswith("=") else 1))
            if operator in {"=", "+=", "-=", "*=", "/=", "%="}:
                target_value = left
                if operator != "=" and re.fullmatch(r"[A-Za-z_]\w*\[.+\]", left):
                    target_value = self.new_temp()
                    self.emit(f"{target_value} = load {left}", line)
                value = (
                    right
                    if operator == "="
                    else f"{target_value} {operator[0]} {right}"
                )
                self.emit(f"{left} = {value}", line)
                left = left
            else:
                temporary = self.new_temp()
                self.emit(f"{temporary} = {left} {operator} {right}", line)
                left = temporary
        if minimum_precedence == 1 and self.token == "?":
            self.take("?")
            true_value = self.parse_expression()
            self.take(":")
            false_value = self.parse_expression()
            temporary = self.new_temp()
            false_label = self.new_label("ternary_false")
            end_label = self.new_label("ternary_end")
            self.emit(f"ifFalse {left} goto {false_label}", line)
            self.emit(f"{temporary} = {true_value}", line)
            self.emit(f"goto {end_label}", line)
            self.emit(f"label {false_label}", line)
            self.emit(f"{temporary} = {false_value}", line)
            self.emit(f"label {end_label}", line)
            left = temporary
        return left

    def parse_unary(self) -> str:
        line = self.line
        if self.token in {"!", "-", "+", "++", "--", "*", "&"}:
            operator = self.take()
            operand = self.parse_unary()
            if operator in {"++", "--"}:
                self.emit(
                    f"{operand} = {operand} {'+' if operator == '++' else '-'} 1",
                    line,
                )
                return operand
            if operator in {"*", "&"}:
                return f"{operator}{operand}"
            temporary = self.new_temp()
            self.emit(f"{temporary} = {operator}{operand}", line)
            return temporary
        return self.parse_primary()

    def parse_primary(self) -> str:
        line = self.line
        if self.token == "(":
            self.take("(")
            value = self.parse_expression()
            self.take(")")
        elif self.token in {"<eof>", "}", ";", "]", ","}:
            raise TacGenerationError(f"Expected an expression at line {self.line}.")
        else:
            value = self.take()
        while True:
            if self.token == "[":
                indices: list[str] = []
                while self.token == "[":
                    self.take("[")
                    indices.append(self.parse_expression())
                    self.take("]")
                value = self.lower_array_access(value, indices, line)
            elif self.token == "(":
                self.take("(")
                arguments: list[str] = []
                while self.token != ")":
                    arguments.append(self.parse_expression())
                    if self.token != ",":
                        break
                    self.take(",")
                self.take(")")
                call = f"{value}({', '.join(arguments)})"
                if self.token == ";" or self.token in {")", ",", "]"}:
                    self.emit(f"call {call}", line)
                    value = f"call_result_{self.temporary + 1}"
                else:
                    temporary = self.new_temp()
                    self.emit(f"{temporary} = call {call}", line)
                    value = temporary
            elif self.token in {"++", "--"}:
                operator = self.take()
                self.emit(
                    f"{value} = {value} {'+' if operator == '++' else '-'} 1",
                    line,
                )
            else:
                break
        return value

    def lower_array_access(self, name: str, indices: list[str], line: int) -> str:
        dimensions = self.array_dimensions.get(name)
        if dimensions and len(indices) > len(dimensions):
            raise TacGenerationError(
                f"Too many subscripts for array '{name}' at line {line}."
            )
        if dimensions:
            terms: list[str] = []
            for index, subscript in enumerate(indices):
                stride = 1
                try:
                    for dimension in dimensions[index + 1 :]:
                        stride *= self.constant_value(dimension)
                except ValueError as exc:
                    raise TacGenerationError(
                        f"Array '{name}' needs constant dimensions for TAC lowering at line {line}."
                    ) from exc
                term = subscript
                if stride != 1:
                    temporary = self.new_temp()
                    self.emit(f"{temporary} = {subscript} * {stride}", line)
                    term = temporary
                terms.append(term)
            offset = terms[0]
            for term in terms[1:]:
                temporary = self.new_temp()
                self.emit(f"{temporary} = {offset} + {term}", line)
                offset = temporary
            if self.token in {"=", "+=", "-=", "*=", "/=", "%="}:
                return f"{name}[{offset}]"
            temporary = self.new_temp()
            self.emit(f"{temporary} = load {name}[{offset}]", line)
            return temporary
        suffix = "".join(f"[{index}]" for index in indices)
        return f"{name}{suffix}"

    def constant_value(self, value: str) -> int:
        if value in self.constants:
            return self.constants[value]
        return int(value)


def _generate_c_tac(source_code: str) -> list[dict[str, Union[int, str]]]:
    return _CTacParser(source_code).parse()


def _c_statement_spans(source_code: str) -> list[tuple[int, int, int, str]]:
    statements: list[tuple[int, int, int, str]] = []
    segment_start = 0
    for semicolon in re.finditer(";", source_code):
        segment = source_code[segment_start:semicolon.start()]
        boundary = max(segment.rfind("{"), segment.rfind("}"))
        statement_start = segment_start + boundary + 1
        text = source_code[statement_start:semicolon.start()]
        comments = C_LEADING_COMMENTS.match(text)
        if comments:
            statement_start += comments.end()
            text = source_code[statement_start:semicolon.start()]
        statements.append(
            (
                statement_start,
                semicolon.end(),
                source_code.count("\n", 0, statement_start) + 1,
                text,
            )
        )
        segment_start = semicolon.end()
    return statements


def parse_c_assignments(source_code: str) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for start, end, line_number, statement in _c_statement_spans(source_code):
        match = C_ASSIGNMENT.match(statement)
        if match:
            expression = match.group("expression").strip()
            if C_SIMPLE_EXPRESSION.fullmatch(expression):
                assignments.append(
                    {
                        "source_line": line_number,
                        "instruction": f"{match.group('target')} = {expression}",
                        "target": match.group("target"),
                        "declaration": (match.group("declaration") or "").strip(),
                        "expression": expression,
                        "start": start + match.start(),
                        "expression_start": start + match.start("expression"),
                        "expression_end": start + match.end("expression"),
                        "end": end,
                    }
                )

    return assignments


def generate_tac(source_code: str, language: str) -> list[dict[str, Union[int, str]]]:
    if language == "python":
        return _generate_python_tac(source_code)
    if language == "c":
        return _generate_c_tac(source_code)
    return []


def _generate_python_tac(source_code: str) -> list[dict[str, Union[int, str]]]:
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    instructions: list[dict[str, Union[int, str]]] = []
    temporary = 0

    def add(line: int, instruction: str) -> None:
        instructions.append({"source_line": line, "instruction": instruction})

    def lower(expression: ast.expr) -> str:
        nonlocal temporary
        if isinstance(expression, ast.BinOp):
            left = lower(expression.left)
            right = lower(expression.right)
            operator = {
                ast.Add: "+",
                ast.Sub: "-",
                ast.Mult: "*",
                ast.Div: "/",
                ast.FloorDiv: "//",
                ast.Mod: "%",
                ast.Pow: "**",
            }.get(type(expression.op))
            if operator is not None:
                temporary += 1
                name = f"t{temporary}"
                add(expression.lineno, f"{name} = {left} {operator} {right}")
                return name
        return ast.unparse(expression)

    def visit(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.FunctionDef):
                visit(statement.body)
            elif isinstance(statement, ast.Assign):
                value = lower(statement.value)
                for target in statement.targets:
                    add(statement.lineno, f"{ast.unparse(target)} = {value}")
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                add(
                    statement.lineno,
                    f"{ast.unparse(statement.target)} = {lower(statement.value)}",
                )
            elif isinstance(statement, ast.AugAssign):
                operator = {
                    ast.Add: "+",
                    ast.Sub: "-",
                    ast.Mult: "*",
                    ast.Div: "/",
                }.get(type(statement.op), ast.unparse(statement.op))
                target = ast.unparse(statement.target)
                add(statement.lineno, f"{target} = {target} {operator} {lower(statement.value)}")
            elif isinstance(statement, ast.Expr):
                if isinstance(statement.value, ast.Call):
                    call = ast.unparse(statement.value)
                    add(statement.lineno, f"call {call}")
                else:
                    add(statement.lineno, lower(statement.value))
            elif isinstance(statement, ast.Return):
                value = lower(statement.value) if statement.value is not None else ""
                add(statement.lineno, f"return {value}".rstrip())
            elif isinstance(statement, (ast.If, ast.While)):
                keyword = "if" if isinstance(statement, ast.If) else "while"
                add(statement.lineno, f"{keyword} {ast.unparse(statement.test)}")
                visit(statement.body)
                visit(statement.orelse)
            elif isinstance(statement, (ast.For, ast.AsyncFor)):
                add(
                    statement.lineno,
                    f"for {ast.unparse(statement.target)} in {ast.unparse(statement.iter)}",
                )
                visit(statement.body)
                visit(statement.orelse)

    visit(tree.body)
    return instructions