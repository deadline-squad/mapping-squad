"""Worker processes that stop the step at the first failure instead of waiting forever.

multiprocessing.Pool replaces a worker whose initializer raised and runs the initializer again, without end, and waits without
end for the task of a worker that was killed (the container's memory limit): render.py on a map whose scene files were missing
ran for 70 minutes and wrote 940 MB of the same traceback (deadline-squad/deadline-squadcalc#34). Pool here is a
concurrent.futures.ProcessPoolExecutor, which marks itself broken when a worker dies, so that every task left raises
BrokenProcessPool. A worker keeps its initializer's error and raises it from each of its tasks: the step stops with that error
(the missing file's name) raised once in the parent, not with a broken pool and a traceback from every worker.
"""

import concurrent.futures

_initializer_error = None


def _start(initializer, initargs):
    """Run a worker's initializer; an exception it raises is kept for the worker's tasks (_call) to raise."""
    global _initializer_error
    try:
        initializer(*initargs)
    except BaseException as error:
        _initializer_error = error


def _call(func, task):
    if _initializer_error is not None:
        raise _initializer_error
    return func(task)


class Pool:
    """``processes`` worker processes, each prepared once by ``initializer(*initargs)``, that run one-argument tasks.

    ``context`` is the multiprocessing context of the workers (the default start method when None). Used as a context manager:
    leaving the block, normally or by an exception, cancels the tasks no worker has begun and waits for the begun ones.
    """

    def __init__(self, processes, initializer, initargs=(), context=None):
        self._executor = concurrent.futures.ProcessPoolExecutor(processes, context, _start, (initializer, initargs))

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._executor.shutdown(cancel_futures=True)

    def submit(self, func, task):
        """concurrent.futures.Future of ``func(task)`` in a worker. Its result() raises what the task or the worker's initializer
        raised, or BrokenProcessPool when a worker died."""
        return self._executor.submit(_call, func, task)

    def imap_unordered(self, func, tasks):
        """``func(task)`` of every task, in the order the workers finish them. Raises at the first task that fails (see submit);
        the tasks no worker has begun are cancelled when the pool's block is left."""
        futures = [self.submit(func, task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            yield future.result()
