from dataclasses import dataclass, field


@dataclass
class StepResult:
    name: str
    status: str   # 'ok' | 'error' | 'skipped'
    detail: str = ''


@dataclass
class PlaybookResult:
    steps: list = field(default_factory=list)
    entry: object = None   # ProxyEntry left alive after failure, for manual recovery

    @property
    def success(self):
        return all(s.status != 'error' for s in self.steps)

    @property
    def failed_step(self):
        return next((s for s in self.steps if s.status == 'error'), None)


class Playbook:
    name: str = ''
    description: str = ''

    def run(self, **inputs) -> PlaybookResult:
        raise NotImplementedError
