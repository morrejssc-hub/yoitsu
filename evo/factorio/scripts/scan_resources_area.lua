-- Scan resources in a rectangular area around specified center
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Parse parameters
    local center_x = tonumber(args.center_x) or 0
    local center_y = tonumber(args.center_y) or 0
    local width = tonumber(args.width) or 100
    local height = tonumber(args.height) or 100
    
    -- Calculate rectangular area bounds
    local half_w = width / 2
    local half_h = height / 2
    local left_top = {x = center_x - half_w, y = center_y - half_h}
    local right_bottom = {x = center_x + half_w, y = center_y + half_h}
    
    -- Get surface (default to nauvis/surfaces[1])
    local surface = game.surfaces[1]
    
    -- Find all resources in the rectangular area
    local resources = surface.find_entities_filtered{
        area = {left_top, right_bottom},
        type = "resource"
    }
    
    -- Aggregate data by resource type
    local aggregated = {}
    local total_entities = 0
    local total_amount = 0
    
    for _, res in ipairs(resources) do
        local name = res.name
        local amount = res.amount or 0
        
        if not aggregated[name] then
            aggregated[name] = {
                count = 0,
                total_amount = 0,
                positions = {}
            }
        end
        
        aggregated[name].count = aggregated[name].count + 1
        aggregated[name].total_amount = aggregated[name].total_amount + amount
        
        -- Store position info (limit to first 10 per type to avoid huge output)
        if aggregated[name].count <= 10 then
            table.insert(aggregated[name].positions, {
                x = math.floor(res.position.x),
                y = math.floor(res.position.y),
                amount = amount
            })
        end
        
        total_entities = total_entities + 1
        total_amount = total_amount + amount
    end
    
    -- Build summary
    local summary = {}
    for name, data in pairs(aggregated) do
        table.insert(summary, {
            name = name,
            count = data.count,
            total_amount = data.total_amount,
            avg_amount = math.floor(data.total_amount / data.count),
            sample_positions = data.positions
        })
    end
    
    -- Sort by total amount descending
    table.sort(summary, function(a, b) return a.total_amount > b.total_amount end)
    
    return serialize({
        ok = true,
        area = {
            center = {x = center_x, y = center_y},
            width = width,
            height = height,
            left_top = {x = math.floor(left_top.x), y = math.floor(left_top.y)},
            right_bottom = {x = math.floor(right_bottom.x), y = math.floor(right_bottom.y)}
        },
        summary = {
            total_types = #summary,
            total_entities = total_entities,
            total_amount = total_amount
        },
        resources = summary
    })
end
