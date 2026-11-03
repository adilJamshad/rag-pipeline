create or replace function current_for(target int)
returns table (rfc int, title text, status text, depth int)
language sql stable as $$
    with recursive chain(n, depth, path) as (
        select target, 0, array[target]
      union all
        select x.src, c.depth + 1, c.path || x.src
          from chain c
          join rfc_relation x on x.dst = c.n and x.kind = 'obsoletes'
         where not x.src = any(c.path)
    )
    select c.n, r.title, r.status, c.depth
      from chain c
      join rfc r on r.number = c.n
     where not exists (
         select 1 from rfc_relation y where y.dst = c.n and y.kind = 'obsoletes'
     )
     order by c.depth, c.n;
$$;
