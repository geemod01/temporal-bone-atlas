import resource, subprocess, sys, time
t = time.time()
p = subprocess.run(sys.argv[1:])
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
print('\npeak RSS of converter: %.0f MB, wall %.0f s, exit %d' % (ru.ru_maxrss / 1024, time.time() - t, p.returncode))
