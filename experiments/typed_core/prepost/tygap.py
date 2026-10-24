"""Why ty 0.0.90 rejects a valid declaration under an expected type, and why
making the condition covariant is no cure (both checkers then widen).

ty solves a method's type variables from the expected return type first:
for ``E[Literal["exists", "read"]]`` it fixes each condition's atom to the
whole union, then an invariant ``Cond[Literal["exists"]]`` no longer fits.
A covariant condition fits, but then an expected type naming more atoms
than were declared is satisfied too. Lines marked E are errors in both
checkers; E-ty in ty only; E-pyright in Pyright only."""

from typing import Generic, Literal, Never, TypeVar


A = TypeVar("A")
Ac = TypeVar("Ac", covariant=True)
X1 = TypeVar("X1")
X2 = TypeVar("X2")
Pre = TypeVar("Pre", contravariant=True, default=Never)


class Cond(Generic[A]): ...  # noqa: UP046


class CondCo(Generic[Ac]): ...  # noqa: UP046


class E(Generic[Pre]):
    def req2(self, c1: Cond[X1], c2: Cond[X2]) -> E[Pre | X1 | X2]:
        raise NotImplementedError

    def req2co(self, c1: CondCo[X1], c2: CondCo[X2]) -> E[Pre | X1 | X2]:
        raise NotImplementedError


ex: Cond[Literal["exists"]] = Cond()
rd: Cond[Literal["read"]] = Cond()
exc: CondCo[Literal["exists"]] = CondCo()
rdc: CondCo[Literal["read"]] = CondCo()
e: E = E()

# invariant condition, no overloads, expected multi-atom type
a: E[Literal["exists", "read"]] = e.req2(ex, rd)  # E-ty: precise, but rejected
# covariant condition: precise?
b: E[Literal["exists", "read"]] = e.req2co(exc, rdc)
# covariant: does it widen (unsound) — demand read, declare only exists twice
c: E[Literal["read"]] = e.req2co(exc, exc)  # E: an atom not declared
d: E[Literal["read"]] = e.req2(ex, ex)  # E: an atom not declared


class E1(Generic[Pre]):
    def req1co(self, c1: CondCo[X1]) -> E1[Pre | X1]:
        raise NotImplementedError

    def req1(self, c1: Cond[X1]) -> E1[Pre | X1]:
        raise NotImplementedError


e1: E1 = E1()
# widening: declares only exists; the expected type also demands read
w1: E1[Literal["exists", "read"]] = e1.req1co(exc)  # covariant: both accept (unsound)
w2: E[Literal["exists", "read"]] = e.req2co(exc, exc)  # E-pyright: ty accepts (unsound)
w3: E1[Literal["exists", "read"]] = e1.req1(ex)  # E: invariant: sound in both
