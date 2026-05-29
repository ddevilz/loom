"""Unit tests for the Ruby structural parser."""

from __future__ import annotations

from loom.graph.models import NodeKind
from loom.indexer.languages.ruby import RubyHandler

RB_SRC = b"""
module Greeting
  class Greeter
    def initialize(name)
      @name = name
    end

    def greet
      "hi #{@name}"
    end
  end

  def self.shout(msg)
    msg.upcase
  end
end
"""


def test_parse_ruby_basic():
    nodes = RubyHandler().parse(RB_SRC, "greet.rb")
    by_name = {n.name: n.kind for n in nodes}
    assert by_name["Greeting"] == NodeKind.CLASS
    assert by_name["Greeter"] == NodeKind.CLASS
    assert any(n.name == "greet" and n.kind == NodeKind.METHOD for n in nodes)
    assert any(n.name == "shout" and n.kind == NodeKind.METHOD for n in nodes)  # class-level method


def test_parse_ruby_assigns_paths_and_language():
    nodes = RubyHandler().parse(RB_SRC, "greet.rb")
    assert all(n.path == "greet.rb" for n in nodes)
    assert all(n.language == "ruby" for n in nodes)


def test_parse_ruby_node_ids_have_correct_prefix():
    nodes = RubyHandler().parse(RB_SRC, "greet.rb")
    for n in nodes:
        assert n.id.startswith(f"{n.kind.value}:")


def test_parse_ruby_line_numbers_set():
    nodes = RubyHandler().parse(RB_SRC, "greet.rb")
    for n in nodes:
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line
