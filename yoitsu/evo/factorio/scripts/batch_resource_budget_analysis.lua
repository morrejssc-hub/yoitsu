-- Batch resource budget analysis for resource consumption vs allocation
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Validate input structure
    if not args.budgets or type(args.budgets) ~= "table" then
        return serialize({error = "missing or invalid 'budgets' array"})
    end
    
    local results = {}
    local total_variance = 0
    local significant_variances = {}
    
    -- Process each budget item
    for i, budget_item in ipairs(args.budgets) do
        if type(budget_item) ~= "table" then
            table.insert(results, {error = "invalid budget item at index " .. i})
        else
            local item_name = budget_item.item
            local allocated = budget_item.allocated or 0
            local actual = budget_item.actual or 0
            
            if not item_name then
                table.insert(results, {error = "missing item name at index " .. i})
            else
                local variance = actual - allocated
                local variance_pct = allocated > 0 and (variance / allocated * 100) or (actual > 0 and 100 or 0)
                
                local result = {
                    item = item_name,
                    allocated = allocated,
                    actual = actual,
                    variance = variance,
                    variance_pct = variance_pct,
                    status = "ok"
                }
                
                -- Flag significant variances (>10% or absolute >100)
                if math.abs(variance_pct) > 10 or math.abs(variance) > 100 then
                    result.significant = true
                    table.insert(significant_variances, result)
                end
                
                total_variance = total_variance + variance
                table.insert(results, result)
            end
        end
    end
    
    -- Calculate summary statistics
    local summary = {
        total_items = #args.budgets,
        items_with_errors = 0,
        total_variance = total_variance,
        significant_count = #significant_variances
    }
    
    -- Count errors
    for _, result in ipairs(results) do
        if result.error then
            summary.items_with_errors = summary.items_with_errors + 1
        end
    end
    
    return serialize({
        ok = true,
        summary = summary,
        results = results,
        significant_variances = significant_variances
    })
end
