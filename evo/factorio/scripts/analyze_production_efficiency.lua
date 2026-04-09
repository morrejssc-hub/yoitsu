-- Analyze production efficiency with batch budget variance analysis for resource consumption vs allocation
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Default parameters
    local radius = args.radius or 50
    local player = game.players[1]
    if not player or not player.valid then
        return serialize({ok = false, error = "no valid player"})
    end
    
    local surface = player.surface
    local pos = player.position
    
    -- Find all assemblers and furnaces in the area (production entities)
    local production_entities = surface.find_entities_filtered{
        area = {
            left_top = {x = pos.x - radius, y = pos.y - radius},
            right_bottom = {x = pos.x + radius, y = pos.y + radius}
        },
        type = {"assembling-machine", "furnace"}
    }
    
    -- Budget tracking table
    local budget_analysis = {
        total_entities = #production_entities,
        active_count = 0,
        idle_count = 0,
        missing_ingredients_count = 0,
        output_full_count = 0,
        detailed_stats = {}
    }
    
    -- Analyze each production entity
    for _, entity in ipairs(production_entities) do
        if not entity.valid then goto continue end
        
        local entity_data = {
            name = entity.name,
            position = {x = entity.position.x, y = entity.position.y},
            status = "unknown",
            recipe = nil,
            input_inventory = {},
            output_inventory = {},
            energy_usage = 0
        }
        
        -- Check if entity has a recipe
        if entity.type == "assembling-machine" or entity.type == "furnace" then
            local recipe = entity.get_recipe()
            if recipe then
                entity_data.recipe = recipe.name
            end
            
            -- Get inventory contents
            if entity.get_inventory(defines.inventory.assembling_machine_input) then
                local input_inv = entity.get_inventory(defines.inventory.assembling_machine_input)
                for _, item in pairs(input_inv.get_contents()) do
                    table.insert(entity_data.input_inventory, {
                        name = item.name,
                        count = item.count
                    })
                end
            end
            
            if entity.get_inventory(defines.inventory.assembling_machine_output) then
                local output_inv = entity.get_inventory(defines.inventory.assembling_machine_output)
                for _, item in pairs(output_inv.get_contents()) do
                    table.insert(entity_data.output_inventory, {
                        name = item.name,
                        count = item.count
                    })
                end
            end
            
            -- Check entity status
            if entity.active then
                entity_data.status = "active"
                budget_analysis.active_count = budget_analysis.active_count + 1
            else
                -- Determine why it's inactive
                local missing_ingredients = false
                local output_full = false
                
                if recipe then
                    -- Check if missing ingredients
                    local ingredients = recipe.ingredients or {}
                    for _, ingredient in ipairs(ingredients) do
                        local has_amount = 0
                        if entity.get_inventory(defines.inventory.assembling_machine_input) then
                            has_amount = entity.get_inventory(defines.inventory.assembling_machine_input).get_item_count(ingredient.name)
                        end
                        if has_amount < ingredient.amount then
                            missing_ingredients = true
                            break
                        end
                    end
                    
                    -- Check if output is full
                    if entity.get_inventory(defines.inventory.assembling_machine_output) then
                        output_full = entity.get_inventory(defines.inventory.assembling_machine_output).is_full()
                    end
                end
                
                if missing_ingredients then
                    entity_data.status = "missing_ingredients"
                    budget_analysis.missing_ingredients_count = budget_analysis.missing_ingredients_count + 1
                elseif output_full then
                    entity_data.status = "output_full"
                    budget_analysis.output_full_count = budget_analysis.output_full_count + 1
                else
                    entity_data.status = "idle"
                    budget_analysis.idle_count = budget_analysis.idle_count + 1
                end
            end
            
            -- Get energy usage if applicable
            if entity.energy then
                entity_data.energy_usage = entity.energy
            end
        end
        
        table.insert(budget_analysis.detailed_stats, entity_data)
        ::continue::
    end
    
    -- Calculate efficiency metrics
    local efficiency = 0
    if budget_analysis.total_entities > 0 then
        efficiency = (budget_analysis.active_count / budget_analysis.total_entities) * 100
    end
    
    -- Budget variance analysis
    local variance_analysis = {
        expected_active = budget_analysis.total_entities,  -- Assuming 100% should be active
        actual_active = budget_analysis.active_count,
        variance = budget_analysis.total_entities - budget_analysis.active_count,
        variance_percentage = 100 - efficiency,
        efficiency_percentage = efficiency
    }
    
    return serialize({
        ok = true,
        budget_analysis = budget_analysis,
        variance_analysis = variance_analysis,
        summary = {
            total_production_units = budget_analysis.total_entities,
            efficiency = string.format("%.2f%%", efficiency),
            issues = {
                missing_ingredients = budget_analysis.missing_ingredients_count,
                output_full = budget_analysis.output_full_count,
                idle = budget_analysis.idle_count
            }
        }
    })
end
