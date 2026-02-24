import pytest
from axon.core.parsers.go_lang import GoParser

@pytest.fixture
def parser():
    return GoParser()

def test_parse_simple_function(parser):
    content = """
    package main
    func Hello() string {
        return "world"
    }
    """
    result = parser.parse(content, "main.go")
    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.name == "Hello"
    assert symbol.kind == "function"
    assert "Hello" in result.exports

def test_parse_struct_and_method(parser):
    content = """
    package main
    type User struct {
        Name string
    }
    func (u *User) GetName() string {
        return u.Name
    }
    """
    result = parser.parse(content, "user.go")
    # 1 struct + 1 method
    assert len(result.symbols) == 2
    
    struct_sym = next(s for s in result.symbols if s.kind == "class")
    assert struct_sym.name == "User"
    
    method_sym = next(s for s in result.symbols if s.kind == "method")
    assert method_sym.name == "GetName"
    assert method_sym.class_name == "User"

def test_parse_imports(parser):
    content = """
    package main
    import (
        "fmt"
        "os"
    )
    func main() {
        fmt.Println(os.Args)
    }
    """
    result = parser.parse(content, "main.go")
    assert len(result.imports) == 2
    modules = {imp.module for imp in result.imports}
    assert "fmt" in modules
    assert "os" in modules
    
    # Check calls
    call_names = {c.name for c in result.calls}
    assert "Println" in call_names

def test_parse_interface(parser):
    content = """
    package main
    type Shaper interface {
        Area() float64
    }
    """
    result = parser.parse(content, "shape.go")
    assert len(result.symbols) == 1
    assert result.symbols[0].name == "Shaper"
    assert result.symbols[0].kind == "interface"
