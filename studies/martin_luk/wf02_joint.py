"""WF02 entry ordering and observation period on the WF01 account rules."""
from . import e15_research as E15, ie47_e1 as IE, wf01_joint as W


def newest_first(book):
    return [[((-e[0][1], e[0][0], e[0][2]),) + tuple(e[1:]) for e in row]
            for row in book]


def build(A, picks, rules, *, c2=False, c3=False, c4=False, c5=False):
    book, episodes, rules, metadata = W.build(A, picks, rules, c1=False, c2=c2, c3=c3)
    if c5:
        book = IE.entry_book(A, picks, **IE.E6['E6a'])[0]
        book, metadata = E15.P.retry_book(A, book, {}, E15.SPECS['C062'])
        book = [[tuple(e[:7]) + (None, .30) + tuple(e[9:]) for e in row] for row in book]
    if c4:
        if rules.make_room_kind:
            raise ValueError('newest-first ordering is incompatible with make_room_kind')
        book = newest_first(book)
    return book, episodes, rules, metadata
