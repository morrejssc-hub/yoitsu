-- Rebuild probe script that returns a simple table
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    
    -- Return a simple table with probe information
    local result = {
        action = "rebuild_probe",
        status = "success",
        tick = game.tick,
        player_count = #game.players,
        force_count = #game.forces
    }
    
    return serialize(result)
end
